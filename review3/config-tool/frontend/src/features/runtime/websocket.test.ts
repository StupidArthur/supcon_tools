import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRuntimeWs } from './websocket'
import type { ConnectionState } from './types'

// Mock WebSocket 测试 helper。
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  static CLOSED = 3

  url: string
  readyState: number = 0
  onopen: ((ev: any) => void) | null = null
  onmessage: ((ev: any) => void) | null = null
  onerror: ((ev: any) => void) | null = null
  onclose: ((ev: any) => void) | null = null
  sentMessages: string[] = []

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string): void {
    this.sentMessages.push(data)
  }

  close(): void {
    this.readyState = FakeWebSocket.CLOSED
    if (this.onclose) this.onclose({})
  }

  // 测试 helper：模拟 open 事件
  triggerOpen(): void {
    this.readyState = FakeWebSocket.OPEN
    if (this.onopen) this.onopen({})
  }

  // 测试 helper：模拟 message 事件
  triggerMessage(data: unknown): void {
    if (this.onmessage) this.onmessage({ data: typeof data === 'string' ? data : JSON.stringify(data) })
  }

  // 测试 helper：模拟 server-side close
  triggerServerClose(): void {
    this.readyState = FakeWebSocket.CLOSED
    if (this.onclose) this.onclose({})
  }
}

describe('createRuntimeWs', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket as any)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('connects to ws://host:port/ws/snapshot', async () => {
    let lastState: ConnectionState = 'idle'
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      (s) => { lastState = s },
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    expect(FakeWebSocket.instances.length).toBe(1)
    expect(FakeWebSocket.instances[0].url).toBe('ws://127.0.0.1:8000/ws/snapshot')
    expect(lastState).toBe('connecting')
    ws.stop()
  })

  it('replaces latestSnapshot on real snapshot message (no data wrapper)', async () => {
    const messages: any[] = []
    const states: ConnectionState[] = []
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      (m) => messages.push(m),
      (s) => states.push(s),
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    const sock = FakeWebSocket.instances[0]
    sock.triggerOpen()
    expect(states).toContain('connected')

    // 关键：snapshot 消息就是完整 dict，不读取 message.data、不额外包装
    sock.triggerMessage({
      cycle_count: 5,
      sim_time: 2.5,
      'valve_1.current_opening': 33.5,
      'tank_2.level': 0.42,
      'pid2.SV': 0.8,
    })
    expect(messages.length).toBe(1)
    expect(messages[0].type).toBe('snapshot')
    expect(messages[0].snapshot.valve.currentOpening).toBe(33.5)
    expect(messages[0].snapshot.tank2.level).toBe(0.42)
    ws.stop()
  })

  it('heartbeat does NOT replace snapshot (only updates heartbeat)', async () => {
    const messages: any[] = []
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      (m) => messages.push(m),
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    const sock = FakeWebSocket.instances[0]
    sock.triggerOpen()
    sock.triggerMessage({
      cycle_count: 1,
      'valve_1.current_opening': 10,
    })
    sock.triggerMessage({ _heartbeat: true, ts: 1234567890 })
    sock.triggerMessage({
      cycle_count: 2,
      'valve_1.current_opening': 20,
    })
    sock.triggerMessage({ _heartbeat: true, ts: 1234567891 })
    // 共 4 条消息：snapshot, heartbeat, snapshot, heartbeat
    expect(messages.length).toBe(4)
    expect(messages[0].type).toBe('snapshot')
    expect(messages[1].type).toBe('heartbeat')
    expect(messages[2].type).toBe('snapshot')
    expect(messages[3].type).toBe('heartbeat')
    // 心跳消息不带 snapshot 字段
    expect(messages[1].snapshot).toBeUndefined()
    expect(messages[3].snapshot).toBeUndefined()
    ws.stop()
  })

  it('exponential backoff reconnect after server-side close', async () => {
    vi.useFakeTimers()
    const states: ConnectionState[] = []
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      (s) => states.push(s),
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    const sock1 = FakeWebSocket.instances[0]
    sock1.triggerOpen()
    expect(states[states.length - 1]).toBe('connected')
    sock1.triggerServerClose()
    expect(states).toContain('disconnected')
    // 第一步 1s 后重连
    await vi.advanceTimersByTimeAsync(1000)
    expect(FakeWebSocket.instances.length).toBe(2)
    // 第二步 2s 后
    FakeWebSocket.instances[1].triggerServerClose()
    await vi.advanceTimersByTimeAsync(2000)
    expect(FakeWebSocket.instances.length).toBe(3)
    // 第三步 4s 后
    FakeWebSocket.instances[2].triggerServerClose()
    await vi.advanceTimersByTimeAsync(4000)
    expect(FakeWebSocket.instances.length).toBe(4)
    ws.stop()
    vi.useRealTimers()
  })

  it('stop() closes WS and prevents reconnect', async () => {
    vi.useFakeTimers()
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    const sock1 = FakeWebSocket.instances[0]
    sock1.triggerOpen()
    sock1.triggerServerClose()
    ws.stop()
    // stop 后即使定时器到了也不应重连
    await vi.advanceTimersByTimeAsync(10000)
    expect(FakeWebSocket.instances.length).toBe(1)
    vi.useRealTimers()
  })

  it('emits state=idle after stop()', async () => {
    const states: ConnectionState[] = []
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      (s) => states.push(s),
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    FakeWebSocket.instances[0].triggerOpen()
    ws.stop()
    expect(states[states.length - 1]).toBe('idle')
  })

  it('fetchSnapshot is called once before WS connects (reconnect-after-REST-first)', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(undefined)
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      { fetchSnapshot: fetchSpy },
    )
    await ws.start()
    expect(fetchSpy).toHaveBeenCalledOnce()
    // WS 在 fetchSnapshot 之后才创建
    expect(FakeWebSocket.instances.length).toBe(1)
    ws.stop()
  })

  it('WS connect failures (factory throws) still schedule reconnect', async () => {
    const failingFactory = () => { throw new Error('boom') }
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      {
        fetchSnapshot: async () => {},
        wsFactory: failingFactory as any,
      },
    )
    await ws.start()
    expect(FakeWebSocket.instances.length).toBe(0) // factory 失败，没创建
    // 此时已 scheduleReconnect，状态应回到 connecting/disconnected
    ws.stop()
  })

  it('does NOT reconnect after stop even if many cycles pass', async () => {
    vi.useFakeTimers()
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    const initialCount = FakeWebSocket.instances.length
    expect(initialCount).toBe(1) // 初次 start 时创建了一个
    ws.stop()
    await vi.advanceTimersByTimeAsync(60000)
    // stop 后即使定时器到点也不应再创建新的 WS 实例
    expect(FakeWebSocket.instances.length).toBe(initialCount)
    vi.useRealTimers()
  })

  it('REAL reconnect order: server-close → backoff → GET snapshot → WS (3rd connection)', async () => {
    vi.useFakeTimers()
    const fetchOrder: string[] = []
    const wsCreated: number[] = [] // 索引 = WS 连接次序
    const factory = (url: string) => {
      const idx = FakeWebSocket.instances.length
      wsCreated.push(idx)
      return new FakeWebSocket(url) as any
    }
    const fetchSnapshot = vi.fn(async () => {
      fetchOrder.push('fetchSnapshot')
    })
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      { fetchSnapshot, wsFactory: factory },
    )

    // 初始 connect → start() 先 fetchSnapshot，再创建 WS #0
    await ws.start()
    expect(fetchOrder).toEqual(['fetchSnapshot'])
    expect(wsCreated).toEqual([0])
    FakeWebSocket.instances[0].triggerOpen()

    // 服务端关闭 → 进入重连流程
    FakeWebSocket.instances[0].triggerServerClose()

    // 第一阶段重连退避 = 1000ms
    await vi.advanceTimersByTimeAsync(999)
    expect(FakeWebSocket.instances.length).toBe(1)
    expect(fetchOrder.length).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(FakeWebSocket.instances.length).toBe(2)
    expect(wsCreated).toEqual([0, 1])

    // 重连 WS #1 onopen → 必须触发 fetchSnapshot（契约：GET snapshot 后继续 WS）
    FakeWebSocket.instances[1].triggerOpen()
    // fetchSnapshot 是 promise；让 microtask 跑完
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchOrder).toEqual(['fetchSnapshot', 'fetchSnapshot'])

    // 第二次关闭 → 第二次重连 → 又 fetchSnapshot + 新 WS
    FakeWebSocket.instances[1].triggerServerClose()
    await vi.advanceTimersByTimeAsync(2000)
    expect(FakeWebSocket.instances.length).toBe(3)
    expect(wsCreated).toEqual([0, 1, 2])
    FakeWebSocket.instances[2].triggerOpen()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchOrder).toEqual(['fetchSnapshot', 'fetchSnapshot', 'fetchSnapshot'])

    // 第三次：退避时间应增加（4s）
    FakeWebSocket.instances[2].triggerServerClose()
    await vi.advanceTimersByTimeAsync(3000)
    expect(FakeWebSocket.instances.length).toBe(3)
    await vi.advanceTimersByTimeAsync(1000)
    expect(FakeWebSocket.instances.length).toBe(4)
    expect(wsCreated.length).toBe(4)
    FakeWebSocket.instances[3].triggerOpen()
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchOrder.length).toBe(4)

    ws.stop()
    vi.useRealTimers()
  })

  it('does not create the reconnect WebSocket until deferred REST snapshot completes', async () => {
    vi.useFakeTimers()
    const order: string[] = []
    let resolveReconnect!: () => void
    let calls = 0
    const fetchSnapshot = vi.fn(async () => {
      calls += 1
      order.push(`rest-${calls}-start`)
      if (calls === 2) {
        await new Promise<void>((resolve) => { resolveReconnect = resolve })
      }
      order.push(`rest-${calls}-done`)
    })
    const factory = (url: string) => {
      order.push(`ws-${FakeWebSocket.instances.length}`)
      return new FakeWebSocket(url) as any
    }
    const client = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      { fetchSnapshot, wsFactory: factory },
    )

    await client.start()
    expect(order).toEqual(['rest-1-start', 'rest-1-done', 'ws-0'])
    FakeWebSocket.instances[0].triggerOpen()
    FakeWebSocket.instances[0].triggerServerClose()

    await vi.advanceTimersByTimeAsync(1000)
    expect(order).toEqual(['rest-1-start', 'rest-1-done', 'ws-0', 'rest-2-start'])
    expect(FakeWebSocket.instances).toHaveLength(1)

    resolveReconnect()
    await vi.advanceTimersByTimeAsync(0)
    expect(order).toEqual([
      'rest-1-start', 'rest-1-done', 'ws-0',
      'rest-2-start', 'rest-2-done', 'ws-1',
    ])
    client.stop()
    vi.useRealTimers()
  })

  it('stop aborts an in-flight reconnect REST and ignores its late completion', async () => {
    vi.useFakeTimers()
    let resolveReconnect!: () => void
    let reconnectSignal: AbortSignal | undefined
    let calls = 0
    const client = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      {
        fetchSnapshot: async (signal) => {
          calls += 1
          if (calls === 2) {
            reconnectSignal = signal
            await new Promise<void>((resolve) => { resolveReconnect = resolve })
          }
        },
      },
    )
    await client.start()
    FakeWebSocket.instances[0].triggerOpen()
    FakeWebSocket.instances[0].triggerServerClose()
    await vi.advanceTimersByTimeAsync(1000)
    expect(FakeWebSocket.instances).toHaveLength(1)

    client.stop()
    expect(reconnectSignal?.aborted).toBe(true)
    resolveReconnect()
    await vi.advanceTimersByTimeAsync(0)
    expect(FakeWebSocket.instances).toHaveLength(1)
    vi.useRealTimers()
  })
})

describe('createRuntimeWs auth token', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket as any)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('appends ?token=... to URL when apiToken is non-empty', async () => {
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5, apiToken: 'secret-token' },
      () => {},
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    expect(FakeWebSocket.instances[0].url).toBe(
      'ws://127.0.0.1:8000/ws/snapshot?token=secret-token',
    )
    ws.stop()
  })

  it('encodes special characters in token', async () => {
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5, apiToken: 'a/b+c d' },
      () => {},
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    expect(FakeWebSocket.instances[0].url).toBe(
      'ws://127.0.0.1:8000/ws/snapshot?token=a%2Fb%2Bc%20d',
    )
    ws.stop()
  })

  it('does NOT append token when apiToken is empty', async () => {
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5, apiToken: '' },
      () => {},
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    expect(FakeWebSocket.instances[0].url).toBe('ws://127.0.0.1:8000/ws/snapshot')
    ws.stop()
  })

  it('does NOT append token when apiToken is undefined', async () => {
    const ws = createRuntimeWs(
      { apiHost: '127.0.0.1', apiPort: 8000, cycleTime: 0.5 },
      () => {},
      () => {},
      { fetchSnapshot: async () => {} },
    )
    await ws.start()
    expect(FakeWebSocket.instances[0].url).toBe('ws://127.0.0.1:8000/ws/snapshot')
    ws.stop()
  })
})
