package main

import (
	"crypto/ecdsa"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/pion/webrtc/v4"
)

// loadCertificate reads the DTLS identity: one PEM file with an
// "EC PRIVATE KEY" and its "CERTIFICATE". The service never creates it
// (the addon does), so every host presents the same fingerprint.
func loadCertificate(path string) (webrtc.Certificate, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return webrtc.Certificate{}, err
	}
	var key *ecdsa.PrivateKey
	var cert *x509.Certificate
	for {
		var b *pem.Block
		b, data = pem.Decode(data)
		if b == nil {
			break
		}
		switch b.Type {
		case "EC PRIVATE KEY":
			if key, err = x509.ParseECPrivateKey(b.Bytes); err != nil {
				return webrtc.Certificate{}, fmt.Errorf("key: %w", err)
			}
		case "CERTIFICATE":
			if cert, err = x509.ParseCertificate(b.Bytes); err != nil {
				return webrtc.Certificate{}, fmt.Errorf("certificate: %w", err)
			}
		}
	}
	if key == nil || cert == nil {
		return webrtc.Certificate{}, errors.New("PEM needs an EC PRIVATE KEY and a CERTIFICATE")
	}
	if !key.PublicKey.Equal(cert.PublicKey) {
		return webrtc.Certificate{}, errors.New("the key does not match the certificate")
	}
	return webrtc.CertificateFromX509(key, cert), nil
}

// sha256Fingerprint is the certificate's fingerprint as the browser's SDP
// carries it: upper-case hex bytes joined by colons.
func sha256Fingerprint(cert webrtc.Certificate) (string, error) {
	fps, err := cert.GetFingerprints()
	if err != nil {
		return "", err
	}
	for _, fp := range fps {
		if fp.Algorithm == "sha-256" {
			return strings.ToUpper(fp.Value), nil
		}
	}
	return "", errors.New("no sha-256 fingerprint")
}
