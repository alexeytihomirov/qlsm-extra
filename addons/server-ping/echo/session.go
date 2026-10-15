package main

import (
	"sync"
	"time"
)

// reuseBlock keeps a closed session's ufrag refused for a while: the
// browser may keep sending consent checks with it, and those must not
// start a fresh session.
var reuseBlock = 2 * time.Minute

// sessions is the limits table: at most maxTotal sessions, at most
// maxPerIP from one source IP, one session per ICE ufrag.
type sessions struct {
	mu       sync.Mutex
	maxTotal int
	maxPerIP int
	byUfrag  map[string]string // ufrag -> source ip
	perIP    map[string]int
	closed   map[string]time.Time // ufrag -> when it was removed
}

func newSessions(maxTotal, maxPerIP int) *sessions {
	return &sessions{
		maxTotal: maxTotal,
		maxPerIP: maxPerIP,
		byUfrag:  map[string]string{},
		perIP:    map[string]int{},
		closed:   map[string]time.Time{},
	}
}

func (s *sessions) add(ufrag, ip string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.byUfrag[ufrag]; ok {
		return false
	}
	if at, ok := s.closed[ufrag]; ok {
		if time.Since(at) < reuseBlock {
			return false
		}
		delete(s.closed, ufrag)
	}
	if len(s.byUfrag) >= s.maxTotal || s.perIP[ip] >= s.maxPerIP {
		return false
	}
	s.byUfrag[ufrag] = ip
	s.perIP[ip]++
	return true
}

func (s *sessions) remove(ufrag string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	ip, ok := s.byUfrag[ufrag]
	if !ok {
		return
	}
	delete(s.byUfrag, ufrag)
	if s.perIP[ip]--; s.perIP[ip] <= 0 {
		delete(s.perIP, ip)
	}
	// The table of closed ufrags stays small: a session needs a slot, so
	// at most a few hundred close within reuseBlock. Prune when it grows.
	if len(s.closed) >= 256 {
		for u, at := range s.closed {
			if time.Since(at) >= reuseBlock {
				delete(s.closed, u)
			}
		}
	}
	s.closed[ufrag] = time.Now()
}

func (s *sessions) has(ufrag string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, ok := s.byUfrag[ufrag]
	return ok
}

func (s *sessions) len() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.byUfrag)
}

// rateLimiter allows at most n events in any sliding window: it remembers
// the times of the last n allowed events.
type rateLimiter struct {
	mu     sync.Mutex
	window time.Duration
	times  []time.Time
	next   int
}

func newRateLimiter(n int, window time.Duration) *rateLimiter {
	return &rateLimiter{window: window, times: make([]time.Time, n)}
}

func (r *rateLimiter) allow(now time.Time) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	oldest := r.times[r.next]
	if !oldest.IsZero() && now.Sub(oldest) < r.window {
		return false
	}
	r.times[r.next] = now
	r.next = (r.next + 1) % len(r.times)
	return true
}
