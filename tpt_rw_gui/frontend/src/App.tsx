import { useState, useEffect } from 'react';
import { VerifyPanel } from '@/components/VerifyPanel';
import { ToastProvider, useToast } from '@/components/Toast';
import { Button, Card, CardContent, CardHeader, CardTitle, Input } from '@/components/ui/primitives';
import { sessionApi, SessionInfo } from '@/lib/api';

const DEFAULT_URL = 'http://10.10.58.153:31501';

function LoginBlock({ info, onLoggedIn }: { info: SessionInfo; onLoggedIn: (i: SessionInfo) => void }) {
  const toast = useToast();
  const [url, setUrl] = useState(info.url || DEFAULT_URL);
  const [tenant, setTenant] = useState(info.tenantId || '');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  async function login() {
    setBusy(true);
    try {
      const res = await sessionApi.login({
        url,
        username,
        password,
        tenantId: tenant,
        timeoutSec: 10,
      });
      toast.push({ kind: 'success', message: '登录成功' });
      onLoggedIn(res);
    } catch (e: unknown) {
      toast.push({ kind: 'error', message: '登录失败: ' + (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    if (busy) return;
    setBusy(true);
    try {
      await sessionApi.logout();
      toast.push({ kind: 'info', message: '已登出' });
      onLoggedIn({ loggedIn: false, url: '', tenantId: '' });
    } catch (e: unknown) {
      toast.push({ kind: 'error', message: '登出失败: ' + (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  if (info.loggedIn) {
    return (
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>登录态</CardTitle>
          <Button variant="outline" disabled={busy} onClick={logout}>登出</Button>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          URL: <span className="font-mono">{info.url}</span>
          {info.tenantId && <span> · tenant: <span className="font-mono">{info.tenantId}</span></span>}
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader><CardTitle>登录</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        <div className="grid grid-cols-12 gap-2">
          <label className="col-span-8 text-sm">URL
            <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://host:port" />
          </label>
          <label className="col-span-4 text-sm">租户 ID(可选)
            <Input value={tenant} onChange={(e) => setTenant(e.target.value)} />
          </label>
        </div>
        <div className="grid grid-cols-12 gap-2">
          <label className="col-span-4 text-sm">用户名
            <Input value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label className="col-span-5 text-sm">密码
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <div className="col-span-3 flex items-end">
            <Button onClick={login} disabled={busy || !url || !username || !password} className="w-full">
              {busy ? '登录中…' : '登录'}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function App() {
  const [session, setSession] = useState<SessionInfo>({ loggedIn: false, url: '', tenantId: '' });
  const [appTitle, setAppTitle] = useState('DataHub读写值验证工具v0.1');
  const handleAuthError = () => {
    setSession({ loggedIn: false, url: '', tenantId: '' });
  };
  useEffect(() => {
    sessionApi.appInfo().then((info) => setAppTitle(info.title)).catch(() => {});
  }, []);
  useEffect(() => {
    if (!session.loggedIn) return;
    let stopped = false;
    const check = async () => {
      try {
        const status = await sessionApi.status();
        if (!stopped && !status.loggedIn) {
          setSession({ loggedIn: false, url: '', tenantId: '' });
        }
      } catch {
      }
    };
    const timer = window.setInterval(check, 30000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [session.loggedIn]);
  return (
    <ToastProvider>
      <div className="min-h-screen bg-background p-6">
        <div className="mx-auto max-w-5xl space-y-4">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold">{appTitle}</h1>
            <span className="text-xs text-muted-foreground">designed by @yuzechao</span>
          </div>
          <LoginBlock info={session} onLoggedIn={setSession} />
          <VerifyPanel disabled={!session.loggedIn} onAuthError={handleAuthError} />
        </div>
      </div>
    </ToastProvider>
  );
}
