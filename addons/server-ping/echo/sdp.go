package main

import "strings"

// remoteOffer is the offer the browser would have sent, rebuilt from its
// ufrag (learned from the STUN USERNAME). Its password and fingerprint are
// dummies: an ICE-lite agent never sends checks, and verification of the
// client's certificate fingerprint is disabled.
func remoteOffer(clientUfrag string) string {
	fp := strings.TrimSuffix(strings.Repeat("00:", 32), ":")
	return "v=0\r\n" +
		"o=- 0 0 IN IP4 0.0.0.0\r\n" +
		"s=-\r\n" +
		"t=0 0\r\n" +
		"a=group:BUNDLE 0\r\n" +
		"m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n" +
		"c=IN IP4 0.0.0.0\r\n" +
		"a=mid:0\r\n" +
		"a=ice-ufrag:" + clientUfrag + "\r\n" +
		"a=ice-pwd:unusedunusedunusedunused\r\n" +
		"a=fingerprint:sha-256 " + fp + "\r\n" +
		"a=setup:actpass\r\n" +
		"a=sctp-port:5000\r\n" +
		"a=max-message-size:16384\r\n"
}
