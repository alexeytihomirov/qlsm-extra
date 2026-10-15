package main

import (
	"testing"
	"time"
)

func TestSessionsLimitPerIP(t *testing.T) {
	s := newSessions(64, 2)
	if !s.add("ufrag1", "203.0.113.1") || !s.add("ufrag2", "203.0.113.1") {
		t.Fatal("first two sessions of one IP must be accepted")
	}
	if s.add("ufrag3", "203.0.113.1") {
		t.Fatal("third session of one IP must be refused")
	}
	if !s.add("ufrag4", "203.0.113.2") {
		t.Fatal("another IP must still be accepted")
	}
}

func TestSessionsLimitTotal(t *testing.T) {
	s := newSessions(3, 2)
	for i, ip := range []string{"203.0.113.1", "203.0.113.2", "203.0.113.3"} {
		if !s.add("ufrag"+string(rune('a'+i)), ip) {
			t.Fatalf("session %d must be accepted", i)
		}
	}
	if s.add("ufragz", "203.0.113.4") {
		t.Fatal("session over the total limit must be refused")
	}
	if s.len() != 3 {
		t.Fatalf("len = %d, want 3", s.len())
	}
}

func TestSessionsRemoveFreesSlot(t *testing.T) {
	s := newSessions(64, 2)
	s.add("ufrag1", "203.0.113.1")
	s.add("ufrag2", "203.0.113.1")
	if s.add("ufrag1", "203.0.113.9") {
		t.Fatal("a ufrag already in use must be refused")
	}
	s.remove("ufrag1")
	s.remove("unknown") // no-op
	if !s.add("ufrag3", "203.0.113.1") {
		t.Fatal("removing a session must free its slot")
	}
	if s.has("ufrag1") {
		t.Fatal("removed session still present")
	}
	if s.len() != 2 {
		t.Fatalf("len = %d, want 2", s.len())
	}
}

func TestSessionsRefuseRecentlyClosedUfrag(t *testing.T) {
	// A browser keeps sending consent checks with the old ufrag for a while;
	// they must not resurrect a session the server already closed.
	s := newSessions(64, 2)
	s.add("ufrag1", "203.0.113.1")
	s.remove("ufrag1")
	if s.add("ufrag1", "203.0.113.1") {
		t.Fatal("a just closed ufrag must not start a new session")
	}
}

func TestRateLimiter(t *testing.T) {
	r := newRateLimiter(50, time.Second)
	t0 := time.Unix(1000, 0)
	for i := 0; i < 50; i++ {
		if !r.allow(t0.Add(time.Duration(i) * time.Millisecond)) {
			t.Fatalf("message %d must be allowed", i)
		}
	}
	if r.allow(t0.Add(100 * time.Millisecond)) {
		t.Fatal("51st message within one second must be refused")
	}
	if !r.allow(t0.Add(time.Second)) {
		t.Fatal("a message one second after the first must be allowed")
	}
	if r.allow(t0.Add(time.Second)) {
		t.Fatal("only one slot freed after one second")
	}
}

func TestSessionsClosedUfragCap(t *testing.T) {
	old := closedCap
	closedCap = 3
	t.Cleanup(func() { closedCap = old })

	s := newSessions(64, 64)
	for _, u := range []string{"ufrag0", "ufrag1", "ufrag2", "ufrag3"} {
		if !s.add(u, "203.0.113.1") {
			t.Fatalf("add %s", u)
		}
		s.remove(u)
	}
	if n := s.closedLen(); n != 3 {
		t.Fatalf("closed table holds %d, want the cap 3", n)
	}
	if !s.add("ufrag0", "203.0.113.1") {
		t.Fatal("the oldest closed ufrag must have been evicted")
	}
	if s.add("ufrag3", "203.0.113.1") {
		t.Fatal("a recently closed ufrag must still be refused")
	}
}
