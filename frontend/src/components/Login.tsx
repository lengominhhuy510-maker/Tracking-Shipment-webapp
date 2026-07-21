export interface AuthUser {
  id: number;
  email: string;
  name: string | null;
  role: string;
  provider: string;
}

interface LoginProps {
  error?: string | null;
}

export default function Login({ error }: LoginProps) {
  return (
    <div className="login-screen">
      <h2>Đăng nhập</h2>
      <p>Chọn nhà cung cấp để tiếp tục theo dõi lô hàng.</p>
      {error && <p className="form-error">{error}</p>}
      <div className="login-buttons">
        <a className="btn-login" href="/auth/login/google">
          Đăng nhập với Google
        </a>
        <a className="btn-login" href="/auth/login/microsoft">
          Đăng nhập với Microsoft
        </a>
      </div>
    </div>
  );
}
