package realtime

import (
	"crypto/sha256"
	"encoding/hex"
	"hash"
)

type revHash struct{ h hash.Hash }

func newRevHash() *revHash { return &revHash{h: sha256.New()} }

func (r *revHash) Write(p []byte) (int, error) { return r.h.Write(p) }

func (r *revHash) sum12() string {
	return hex.EncodeToString(r.h.Sum(nil))[:12]
}

func sha256File(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}