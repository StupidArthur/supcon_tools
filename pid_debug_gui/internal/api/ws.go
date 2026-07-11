package api

import (
	"encoding/json"
	"fmt"
	"log"
	"net/url"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

type WsClient struct {
	mu          sync.Mutex
	conn        *websocket.Conn
	baseURL     string
	connected   bool
	stopCh      chan struct{}
	snapshotCh  chan map[string]float64
	onSnapshot  func(map[string]float64)
	reconnectCh chan struct{}
}

func NewWsClient(baseURL string) *WsClient {
	return &WsClient{
		baseURL:     baseURL,
		stopCh:      make(chan struct{}),
		snapshotCh:  make(chan map[string]float64, 200),
		reconnectCh: make(chan struct{}, 1),
	}
}

func (w *WsClient) SetOnSnapshot(fn func(map[string]float64)) {
	w.onSnapshot = fn
}

func (w *WsClient) Connect() error {
	u, err := url.Parse(w.baseURL)
	if err != nil {
		return fmt.Errorf("parse URL: %w", err)
	}
	u.Scheme = "ws"
	u.Path = "/ws/snapshot"

	conn, _, err := websocket.DefaultDialer.Dial(u.String(), nil)
	if err != nil {
		return fmt.Errorf("dial %s: %w", u.String(), err)
	}

	w.mu.Lock()
	w.conn = conn
	w.connected = true
	w.mu.Unlock()

	go w.readLoop()
	log.Printf("WS connected to %s", u.String())
	return nil
}

func (w *WsClient) Disconnect() {
	w.mu.Lock()
	defer w.mu.Unlock()
	if !w.connected {
		return
	}
	close(w.stopCh)
	w.conn.Close()
	w.connected = false
	log.Println("WS disconnected")
}

func (w *WsClient) IsConnected() bool {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.connected
}

func (w *WsClient) readLoop() {
	defer func() {
		w.mu.Lock()
		w.connected = false
		w.mu.Unlock()
	}()

	for {
		select {
		case <-w.stopCh:
			return
		default:
		}

		_, message, err := w.conn.ReadMessage()
		if err != nil {
			log.Printf("WS read error: %v, reconnecting in 3s...", err)
			time.Sleep(3 * time.Second)
			if err := w.Connect(); err != nil {
				log.Printf("WS reconnect failed: %v", err)
			}
			return
		}

		var data map[string]float64
		if err := json.Unmarshal(message, &data); err != nil {
			continue
		}

		if _, ok := data["_heartbeat"]; ok {
			continue
		}

		if w.onSnapshot != nil {
			w.onSnapshot(data)
		}
	}
}
