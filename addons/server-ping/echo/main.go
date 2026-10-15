// ql-ping-echo: WebRTC DataChannel UDP echo without a signalling server.
//
// The browser builds this server's SDP itself (ip, port, the shared DTLS
// fingerprint, a random ICE ufrag it also uses as the password). The server
// learns that ufrag from the first STUN binding request (USERNAME
// "<server>:<client>") and creates a matching PeerConnection: ICE-lite, DTLS
// server, negotiated channel id 0. That first request is dropped by the mux
// (no connection for the ufrag yet); the client's retransmit connects.
//
// Source IPs are only kept in memory for the per-IP limit, never logged.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/netip"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/pion/ice/v4"
	"github.com/pion/logging"
	"github.com/pion/stun/v4"
	"github.com/pion/webrtc/v4"
)

const version = "1.0.0"

// Limits; variables so tests can shorten them.
var (
	sessionLifetime      = 60 * time.Second
	idleTimeout          = 10 * time.Second
	connectTimeout       = 10 * time.Second // channel not open yet
	maxMessageSize       = 32
	maxMessagesPerSecond = 50
)

type server struct {
	conn            net.PacketConn
	cert            webrtc.Certificate
	sessions        *sessions
	includeLoopback bool
	logf            func(format string, args ...any)

	mux    *ice.UDPMuxDefault
	active sync.Map // ufrag -> func() closing the session
}

func newServer(conn net.PacketConn, cert webrtc.Certificate, st *sessions) *server {
	return &server{conn: conn, cert: cert, sessions: st, logf: log.Printf}
}

// discardLoggers silences pion: its ICE/DTLS/SCTP warnings and errors can
// carry remote addresses, and under systemd stderr goes to journald on disk.
type discardLoggers struct{}

func (discardLoggers) NewLogger(string) logging.LeveledLogger { return discardLogger{} }

type discardLogger struct{}

func (discardLogger) Trace(string)          {}
func (discardLogger) Tracef(string, ...any) {}
func (discardLogger) Debug(string)          {}
func (discardLogger) Debugf(string, ...any) {}
func (discardLogger) Info(string)           {}
func (discardLogger) Infof(string, ...any)  {}
func (discardLogger) Warn(string)           {}
func (discardLogger) Warnf(string, ...any)  {}
func (discardLogger) Error(string)          {}
func (discardLogger) Errorf(string, ...any) {}

func (s *server) muxParams() ice.UDPMuxParams {
	return ice.UDPMuxParams{UDPConn: s.conn, OnUnhandledPacket: s.onUnhandled, Logger: discardLogger{}}
}

func (s *server) start() {
	s.mux = ice.NewUDPMuxDefault(s.muxParams())
}

// done is closed when the mux has closed: after close(), or because reading
// the UDP socket failed (the mux closes itself then). The mux exposes only
// IsClosed, so it is polled.
func (s *server) done() <-chan struct{} {
	ch := make(chan struct{})
	go func() {
		t := time.NewTicker(500 * time.Millisecond)
		defer t.Stop()
		for range t.C {
			if s.mux.IsClosed() {
				close(ch)
				return
			}
		}
	}()
	return ch
}

func (s *server) close() {
	s.active.Range(func(_, v any) bool {
		v.(func())()
		return true
	})
	if s.mux != nil {
		_ = s.mux.Close()
	}
}

// iceChars reports whether v is a valid ICE ufrag (RFC 8839 ice-char). The
// client's ufrag is put into an SDP, so anything else is refused.
func iceChars(v string, minLen, maxLen int) bool {
	if len(v) < minLen || len(v) > maxLen {
		return false
	}
	for _, c := range v {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '+' || c == '/') {
			return false
		}
	}
	return true
}

// onUnhandled is called by the mux, synchronously, for every packet it
// cannot route. A binding request of an unknown ufrag starts a session.
func (s *server) onUnhandled(data []byte, addr netip.AddrPort) {
	if !stun.IsMessage(data) {
		return
	}
	m := &stun.Message{Raw: append([]byte(nil), data...)}
	if m.Decode() != nil || m.Type != stun.BindingRequest {
		return
	}
	var u stun.Username
	if u.GetFrom(m) != nil {
		return
	}
	local, remote, ok := strings.Cut(u.String(), ":")
	if !ok || !iceChars(local, 4, 64) || !iceChars(remote, 4, 256) {
		return
	}
	if !s.sessions.add(local, addr.Addr().Unmap().String()) {
		return
	}
	go func() {
		if err := s.serve(local, remote); err != nil {
			s.logf("session setup failed: %v", err)
		}
	}()
}

// serve creates the PeerConnection for one session. The session is removed
// from the table when it closes: connection lost, idle or lifetime over.
func (s *server) settingEngine(local string) *webrtc.SettingEngine {
	se := &webrtc.SettingEngine{LoggerFactory: discardLoggers{}}
	se.SetLite(true)
	se.SetICEUDPMux(s.mux)
	se.SetICECredentials(local, local)
	se.SetNetworkTypes([]webrtc.NetworkType{webrtc.NetworkTypeUDP4})
	se.DisableCertificateFingerprintVerification(true)
	_ = se.SetAnsweringDTLSRole(webrtc.DTLSRoleServer) // fails only for roles other than client/server
	se.SetIncludeLoopbackCandidate(s.includeLoopback)
	return se
}

func (s *server) serve(local, remote string) error {
	api := webrtc.NewAPI(webrtc.WithSettingEngine(*s.settingEngine(local)))
	pc, err := api.NewPeerConnection(webrtc.Configuration{Certificates: []webrtc.Certificate{s.cert}})
	if err != nil {
		s.sessions.remove(local)
		return err
	}

	idle := idleTimeout
	var (
		once     sync.Once
		mu       sync.Mutex
		closed   bool
		idleT    *time.Timer
		lifeT    *time.Timer
		closeAll func()
	)
	closeAll = func() {
		once.Do(func() {
			mu.Lock()
			closed = true
			if idleT != nil {
				idleT.Stop()
				lifeT.Stop()
			}
			mu.Unlock()
			_ = pc.Close()
			s.active.Delete(local)
			s.sessions.remove(local)
		})
	}
	// touch never re-arms the idle timer of a closed session.
	touch := func() {
		mu.Lock()
		if !closed {
			idleT.Reset(idle)
		}
		mu.Unlock()
	}
	// Registered before the timers exist, so server.close() always sees it.
	s.active.Store(local, closeAll)
	mu.Lock()
	if closed {
		mu.Unlock()
		return nil
	}
	// Until the channel opens the idle timer is the connect timeout.
	idleT = time.AfterFunc(connectTimeout, func() { closeAll() })
	lifeT = time.AfterFunc(sessionLifetime, func() { closeAll() })
	mu.Unlock()

	fail := func(err error) error {
		closeAll()
		return err
	}

	neg, ordered, id, maxRe := true, false, uint16(0), uint16(0)
	dc, err := pc.CreateDataChannel("ping", &webrtc.DataChannelInit{Negotiated: &neg, ID: &id, Ordered: &ordered, MaxRetransmits: &maxRe})
	if err != nil {
		return fail(err)
	}
	limiter := newRateLimiter(maxMessagesPerSecond, time.Second)
	dc.OnOpen(touch)
	dc.OnMessage(func(m webrtc.DataChannelMessage) {
		touch()
		if len(m.Data) > maxMessageSize || !limiter.allow(time.Now()) {
			return
		}
		if m.IsString {
			_ = dc.SendText(string(m.Data))
		} else {
			_ = dc.Send(m.Data)
		}
	})
	pc.OnConnectionStateChange(func(st webrtc.PeerConnectionState) {
		switch st {
		case webrtc.PeerConnectionStateFailed, webrtc.PeerConnectionStateClosed, webrtc.PeerConnectionStateDisconnected:
			go closeAll()
		}
	})
	if err := pc.SetRemoteDescription(webrtc.SessionDescription{Type: webrtc.SDPTypeOffer, SDP: remoteOffer(remote)}); err != nil {
		return fail(fmt.Errorf("remote description: %w", err))
	}
	answer, err := pc.CreateAnswer(nil)
	if err != nil {
		return fail(err)
	}
	if err := pc.SetLocalDescription(answer); err != nil {
		return fail(err)
	}
	return nil
}

type options struct {
	listen   string
	cert     string
	maxTotal int
	maxPerIP int
	version  bool
}

func parseFlags(args []string, stderr io.Writer) (options, error) {
	var o options
	fs := flag.NewFlagSet("ql-ping-echo", flag.ContinueOnError)
	fs.SetOutput(stderr)
	fs.StringVar(&o.listen, "listen", ":28111", "UDP listen address (IPv4)")
	fs.StringVar(&o.cert, "cert", "/etc/ql-ping-echo/cert.pem", "PEM with EC PRIVATE KEY and CERTIFICATE (created by the server-ping addon, never by this service)")
	fs.IntVar(&o.maxTotal, "max", 64, "max concurrent sessions")
	fs.IntVar(&o.maxPerIP, "per-ip", 2, "max concurrent sessions per source IP")
	fs.BoolVar(&o.version, "version", false, "print the version and exit")
	err := fs.Parse(args)
	return o, err
}

// wait blocks until a signal (exit 0) or until the UDP socket died (exit 1,
// so systemd restarts the service).
func wait(srv *server, sig <-chan os.Signal, logger *log.Logger) int {
	select {
	case <-sig:
		srv.close()
		return 0
	case <-srv.done():
		srv.close()
		logger.Printf("UDP socket closed, exiting")
		return 1
	}
}

func run(args []string, stdout, stderr io.Writer) int {
	o, err := parseFlags(args, stderr)
	if err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return 0
		}
		return 2
	}
	if o.version {
		fmt.Fprintf(stdout, "ql-ping-echo %s\n", version)
		return 0
	}
	logger := log.New(stderr, "", 0) // journald adds the timestamps

	cert, err := loadCertificate(o.cert)
	if err != nil {
		logger.Printf("certificate %s: %v", o.cert, err)
		return 1
	}
	fp, err := sha256Fingerprint(cert)
	if err != nil {
		logger.Printf("certificate %s: %v", o.cert, err)
		return 1
	}
	fmt.Fprintf(stdout, "fingerprint sha-256 %s\n", fp)

	conn, err := net.ListenPacket("udp4", o.listen)
	if err != nil {
		logger.Printf("listen: %v", err)
		return 1
	}
	srv := newServer(conn, cert, newSessions(o.maxTotal, o.maxPerIP))
	srv.logf = logger.Printf
	srv.start()
	logger.Printf("ql-ping-echo %s listening on %s", version, conn.LocalAddr())

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	return wait(srv, sig, logger)
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}
