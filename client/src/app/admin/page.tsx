'use client';

import Link from 'next/link';
import {useRouter} from 'next/navigation';
import {useEffect, useRef, useState, type FormEvent} from 'react';
import {ArrowUpRight} from 'lucide-react';
import {api, ApiError, type User} from '@/lib/api';

export default function AdminLogin() {
  const router = useRouter();
  const submitting = useRef(false);
  const [checking, setChecking] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    api<User>('/v1/me').then(() => {
      if (live) router.replace('/');
    }).catch((reason: unknown) => {
      if (!live) return;
      if (!(reason instanceof ApiError && reason.status === 401)) {
        setError(reason instanceof Error ? reason.message : '서버에 연결하지 못했습니다.');
      }
      setChecking(false);
    });
    return () => { live = false; };
  }, [router]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setPending(true);
    setError('');
    const form = event.currentTarget;
    const values = new FormData(form);
    try {
      await api('/auth/admin', {method: 'POST', body: JSON.stringify({
        username: values.get('username'), password: values.get('password'),
      })});
      await api<User>('/v1/me');
      form.reset();
      window.location.replace('/');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '로그인하지 못했습니다. 다시 시도해 주세요.');
      submitting.current = false;
      setPending(false);
    }
  }

  return <main className="admin-login">
    <section className="admin-login-content" aria-labelledby="admin-title">
      <Link href="/" className="brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/><i/></span>모두라우터</Link>
      <h1 id="admin-title">관리자 로그인</h1>
      <p className="muted">아이디와 비밀번호로 로그인하세요. 로그인 후 모든 회원 기능을 사용할 수 있습니다.</p>
      {checking ? <p role="status">로그인 상태를 확인하고 있습니다.</p> : <form className="admin-login-form" onSubmit={login} aria-busy={pending}>
        <label htmlFor="admin-username">아이디</label>
        <input id="admin-username" name="username" autoComplete="username" required maxLength={255} disabled={pending} aria-describedby={error ? 'admin-error' : undefined}/>
        <label htmlFor="admin-password">비밀번호</label>
        <input id="admin-password" name="password" type="password" autoComplete="current-password" required maxLength={1024} disabled={pending} aria-describedby={error ? 'admin-error' : undefined}/>
        {error && <p id="admin-error" role="alert" className="error">{error}</p>}
        <button className="primary" type="submit" disabled={pending}>{pending ? '로그인 중' : '로그인'}<ArrowUpRight/></button>
      </form>}
      <Link href="/">첫 화면으로 돌아가기</Link>
    </section>
  </main>;
}
