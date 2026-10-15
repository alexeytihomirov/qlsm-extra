package main

import (
	"bytes"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	"github.com/pion/ice/v4"
	"github.com/pion/webrtc/v4"
)

// writeTestPEM creates a key + certificate the way the addon will
// (EC PRIVATE KEY + CERTIFICATE in one file).
func writeTestPEM(t *testing.T) string {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "ql-ping-echo-test"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	kder, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	out := pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: kder})
	out = append(out, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})...)
	path := filepath.Join(t.TempDir(), "cert.pem")
	if err := os.WriteFile(path, out, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadCertificate(t *testing.T) {
	cert, err := loadCertificate(writeTestPEM(t))
	if err != nil {
		t.Fatal(err)
	}
	fp, err := sha256Fingerprint(cert)
	if err != nil {
		t.Fatal(err)
	}
	if !regexp.MustCompile(`^([0-9A-F]{2}:){31}[0-9A-F]{2}$`).MatchString(fp) {
		t.Fatalf("fingerprint %q is not 32 upper-case hex bytes", fp)
	}
}

func TestLoadCertificateRejectsBadInput(t *testing.T) {
	dir := t.TempDir()
	if _, err := loadCertificate(filepath.Join(dir, "missing.pem")); err == nil {
		t.Fatal("missing file must fail")
	}
	garbage := filepath.Join(dir, "garbage.pem")
	_ = os.WriteFile(garbage, []byte("not a pem"), 0o600)
	if _, err := loadCertificate(garbage); err == nil {
		t.Fatal("garbage must fail")
	}
	// Certificate only, no key.
	full, _ := os.ReadFile(writeTestPEM(t))
	certOnly := filepath.Join(dir, "cert-only.pem")
	_ = os.WriteFile(certOnly, full[bytes.Index(full, []byte("-----BEGIN CERTIFICATE")):], 0o600)
	if _, err := loadCertificate(certOnly); err == nil {
		t.Fatal("PEM without a key must fail")
	}
	// Key of one pair, certificate of another.
	a, _ := os.ReadFile(writeTestPEM(t))
	b, _ := os.ReadFile(writeTestPEM(t))
	mixed := filepath.Join(dir, "mixed.pem")
	mix := append(append([]byte{}, a[:bytes.Index(a, []byte("-----BEGIN CERTIFICATE"))]...), b[bytes.Index(b, []byte("-----BEGIN CERTIFICATE")):]...)
	_ = os.WriteFile(mixed, mix, 0o600)
	if _, err := loadCertificate(mixed); err == nil {
		t.Fatal("key not matching the certificate must fail")
	}
}

func TestRunFailsWithoutPEM(t *testing.T) {
	var out, errb bytes.Buffer
	path := filepath.Join(t.TempDir(), "none.pem")
	code := run([]string{"-listen", "127.0.0.1:0", "-cert", path}, &out, &errb)
	if code == 0 {
		t.Fatal("missing PEM must exit non-zero")
	}
	if _, err := os.Stat(path); err == nil {
		t.Fatal("the service must never create the PEM")
	}
}

func TestRunVersion(t *testing.T) {
	var out, errb bytes.Buffer
	if code := run([]string{"-version"}, &out, &errb); code != 0 {
		t.Fatalf("exit %d", code)
	}
	if !strings.Contains(out.String(), version) {
		t.Fatalf("version output %q", out.String())
	}
}

type testServer struct {
	srv  *server
	ip   string
	port int
	fp   string
}

func startServer(t *testing.T) *testServer {
	t.Helper()
	cert, err := loadCertificate(writeTestPEM(t))
	if err != nil {
		t.Fatal(err)
	}
	fp, err := sha256Fingerprint(cert)
	if err != nil {
		t.Fatal(err)
	}
	conn, err := net.ListenPacket("udp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := newServer(conn, cert, newSessions(64, 2))
	srv.includeLoopback = true // production listens on a public address
	srv.start()
	t.Cleanup(srv.close)
	addr := conn.LocalAddr().(*net.UDPAddr)
	return &testServer{srv: srv, ip: addr.IP.String(), port: addr.Port, fp: fp}
}

// serverAnswer is a copy of the browser's serverAnswer() (ping.html): the
// client invents the server's SDP from ip, port and the shared fingerprint.
func serverAnswer(offerSDP, ip string, port int, fp, ufrag string) string {
	mid := "0"
	if m := regexp.MustCompile(`a=mid:(\S+)`).FindStringSubmatch(offerSDP); m != nil {
		mid = m[1]
	}
	return strings.Join([]string{
		"v=0", "o=- 0 0 IN IP4 " + ip, "s=-", "t=0 0", "a=ice-lite", "a=group:BUNDLE " + mid,
		fmt.Sprintf("m=application %d UDP/DTLS/SCTP webrtc-datachannel", port), "c=IN IP4 " + ip, "a=mid:" + mid,
		"a=ice-ufrag:" + ufrag, "a=ice-pwd:" + ufrag, "a=fingerprint:sha-256 " + fp, "a=setup:passive",
		"a=sctp-port:5000", "a=max-message-size:16384",
		fmt.Sprintf("a=candidate:1 1 udp 2130706431 %s %d typ host", ip, port), "a=end-of-candidates", "",
	}, "\r\n")
}

func randomUfrag(t *testing.T) string {
	t.Helper()
	const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		t.Fatal(err)
	}
	for i := range b {
		b[i] = alphabet[int(b[i])%len(alphabet)]
	}
	return string(b)
}

type testClient struct {
	pc  *webrtc.PeerConnection
	dc  *webrtc.DataChannel
	msg chan []byte
}

// dial connects like the browser: negotiated channel id 0, unordered, no
// retransmits, server SDP built locally.
func dial(t *testing.T, ts *testServer) *testClient {
	t.Helper()
	var se webrtc.SettingEngine
	se.SetNetworkTypes([]webrtc.NetworkType{webrtc.NetworkTypeUDP4})
	se.SetIncludeLoopbackCandidate(true)
	se.SetIPFilter(func(ip net.IP) bool { return ip.IsLoopback() })
	se.SetICEMulticastDNSMode(ice.MulticastDNSModeDisabled)
	api := webrtc.NewAPI(webrtc.WithSettingEngine(se))
	pc, err := api.NewPeerConnection(webrtc.Configuration{})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = pc.Close() })

	neg, ordered, id, maxRe := true, false, uint16(0), uint16(0)
	dc, err := pc.CreateDataChannel("ping", &webrtc.DataChannelInit{Negotiated: &neg, ID: &id, Ordered: &ordered, MaxRetransmits: &maxRe})
	if err != nil {
		t.Fatal(err)
	}
	c := &testClient{pc: pc, dc: dc, msg: make(chan []byte, 256)}
	opened := make(chan struct{})
	dc.OnOpen(func() { close(opened) })
	dc.OnMessage(func(m webrtc.DataChannelMessage) { c.msg <- append([]byte(nil), m.Data...) })

	offer, err := pc.CreateOffer(nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := pc.SetLocalDescription(offer); err != nil {
		t.Fatal(err)
	}
	answer := serverAnswer(offer.SDP, ts.ip, ts.port, ts.fp, randomUfrag(t))
	if err := pc.SetRemoteDescription(webrtc.SessionDescription{Type: webrtc.SDPTypeAnswer, SDP: answer}); err != nil {
		t.Fatal(err)
	}
	select {
	case <-opened:
	case <-time.After(5 * time.Second):
		t.Fatalf("connect timeout, state %s", pc.ConnectionState())
	}
	return c
}

func payload(n int, tag byte) []byte {
	b := make([]byte, n)
	for i := range b {
		b[i] = tag + byte(i)
	}
	return b
}

func (c *testClient) expectEcho(t *testing.T, want []byte, within time.Duration) {
	t.Helper()
	select {
	case got := <-c.msg:
		if !bytes.Equal(got, want) {
			t.Fatalf("echo = %x, want %x", got, want)
		}
	case <-time.After(within):
		t.Fatalf("no echo within %s", within)
	}
}

func TestEchoEndToEnd(t *testing.T) {
	ts := startServer(t)
	c := dial(t, ts)
	if n := ts.srv.sessions.len(); n != 1 {
		t.Fatalf("sessions = %d, want 1", n)
	}
	msg := payload(16, 1)
	if err := c.dc.Send(msg); err != nil {
		t.Fatal(err)
	}
	c.expectEcho(t, msg, 2*time.Second)
}

func TestEchoDropsOversizedMessage(t *testing.T) {
	ts := startServer(t)
	c := dial(t, ts)
	if err := c.dc.Send(payload(33, 1)); err != nil {
		t.Fatal(err)
	}
	select {
	case got := <-c.msg:
		t.Fatalf("oversized message echoed: %d bytes", len(got))
	case <-time.After(500 * time.Millisecond):
	}
	// The session is still alive: a 32-byte message comes back.
	ok := payload(32, 7)
	if err := c.dc.Send(ok); err != nil {
		t.Fatal(err)
	}
	c.expectEcho(t, ok, 2*time.Second)
}

func TestEchoRateLimit(t *testing.T) {
	ts := startServer(t)
	c := dial(t, ts)
	for i := 0; i < 80; i++ {
		if err := c.dc.Send(payload(8, byte(i))); err != nil {
			t.Fatal(err)
		}
	}
	got := 0
	deadline := time.After(700 * time.Millisecond)
loop:
	for {
		select {
		case <-c.msg:
			got++
		case <-deadline:
			break loop
		}
	}
	if got > maxMessagesPerSecond || got < maxMessagesPerSecond-10 {
		t.Fatalf("echoed %d of 80 burst messages, want about %d", got, maxMessagesPerSecond)
	}
}

func TestIdleSessionCloses(t *testing.T) {
	old := idleTimeout
	idleTimeout = 200 * time.Millisecond
	t.Cleanup(func() { idleTimeout = old })

	ts := startServer(t)
	c := dial(t, ts)
	msg := payload(16, 3)
	if err := c.dc.Send(msg); err != nil {
		t.Fatal(err)
	}
	c.expectEcho(t, msg, time.Second)
	time.Sleep(500 * time.Millisecond)
	if n := ts.srv.sessions.len(); n != 0 {
		t.Fatalf("idle session still in the table (%d)", n)
	}
}

func TestFlagDefaults(t *testing.T) {
	o, err := parseFlags(nil, io.Discard)
	if err != nil {
		t.Fatal(err)
	}
	if o.listen != ":28111" || o.cert != "/etc/ql-ping-echo/cert.pem" || o.maxTotal != 64 || o.maxPerIP != 2 || o.version {
		t.Fatalf("defaults = %+v", o)
	}
}

func TestPionLogsDiscarded(t *testing.T) {
	// pion's ICE/DTLS/SCTP loggers may print remote addresses; under
	// systemd stderr goes to journald on disk, so they are all discarded.
	srv := newServer(nil, webrtc.Certificate{}, newSessions(64, 2))
	if _, ok := srv.settingEngine("abcd").LoggerFactory.(discardLoggers); !ok {
		t.Fatal("the session SettingEngine must use the discarding logger factory")
	}
	if _, ok := srv.muxParams().Logger.(discardLogger); !ok {
		t.Fatal("the UDP mux must use the discarding logger")
	}
}

func TestWaitExitsWhenSocketDies(t *testing.T) {
	ts := startServer(t)
	code := make(chan int, 1)
	go func() { code <- wait(ts.srv, make(chan os.Signal), log.New(io.Discard, "", 0)) }()
	_ = ts.srv.conn.Close()
	select {
	case c := <-code:
		if c == 0 {
			t.Fatal("a dead UDP socket must exit non-zero")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("process keeps running with a dead UDP socket")
	}
}

func TestWaitSignalExitsCleanly(t *testing.T) {
	ts := startServer(t)
	sig := make(chan os.Signal, 1)
	code := make(chan int, 1)
	go func() { code <- wait(ts.srv, sig, log.New(io.Discard, "", 0)) }()
	sig <- os.Interrupt
	select {
	case c := <-code:
		if c != 0 {
			t.Fatalf("exit %d on a signal, want 0", c)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("no exit on a signal")
	}
}
