package main

import (
	"sync"
	"time"
)

// reuseBlock keeps a closed session's ufrag refused for a while: the
// browser may keep sending consent checks with it, and those must not
// start a fresh session.
var reuseBlock = 2 * time.Minute

// closedCap bounds the table of closed ufrags; the oldest is forgotten
// first. A session needs a slot, so far fewer close within reuseBlock.
var closedCap = 4096

type closedUfrag struct {
	ufrag string
	at    time.Time
}

// sessions is the limits table: at most maxTotal sessions, at most
// maxPerIP from one source IP, one session per ICE ufrag.
type sessions struct {
	mu       sync.Mutex
	maxTotal int
	maxPerIP int
	byUfrag  map[string]string // ufrag -> source ip
	perIP    map[string]int
	closed   map[string]time.Time // ufrag -> when it was removed
	order    []closedUfrag        // ring, oldest at head, capacity closedCap
	head     int
}

func newSessions(maxTotal, maxPerIP int) *sessions {
	return &sessions{
		maxTotal: maxTotal,
		maxPerIP: maxPerIP,
		byUfrag:  map[string]string{},
		perIP:    map[string]int{},
		closed:   map[string]time.Time{},
		order:    make([]closedUfrag, 0, closedCap),
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
	s.rememberClosed(ufrag, time.Now())
}

// rememberClosed records a closed ufrag in O(1): when the ring is full the
// oldest entry is overwritten and dropped from the map (unless that ufrag
// was recorded again later).
func (s *sessions) rememberClosed(ufrag string, at time.Time) {
	if cap(s.order) == 0 {
		return
	}
	e := closedUfrag{ufrag, at}
	if len(s.order) < cap(s.order) {
		s.order = append(s.order, e)
	} else {
		old := s.order[s.head]
		if t, ok := s.closed[old.ufrag]; ok && t.Equal(old.at) {
			delete(s.closed, old.ufrag)
		}
		s.order[s.head] = e
		s.head = (s.head + 1) % len(s.order)
	}
	s.closed[ufrag] = at
}

func (s *sessions) closedLen() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.closed)
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
