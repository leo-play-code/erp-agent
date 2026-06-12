"""外部登入後端：向公司既有的 mail（IMAP）或目錄（LDAP/AD）驗證員工帳密（模式 B）。

不存任何密碼——只在登入當下拿員工輸入的帳密去公司伺服器試登入，成功即通過。哪些人能登入
由管理員在後台建檔（允許名單）控制（見 control_plane.verify_credentials）。設定放在每間公司的
companies.auth_config（JSON）。

auth_config 範例：
  IMAP： {"host": "mail.acme.com", "port": 993, "ssl": true, "login_format": "{email}"}
  LDAP/AD： {"url": "ldap://dc.acme.com:389", "ssl": false, "user_template": "{email}"}
    user_template 佔位：{email}=完整信箱（AD 常用 UPN）、{local}=@ 前的帳號。
"""

import imaplib

_TIMEOUT = int(__import__("os").getenv("EXTERNAL_AUTH_TIMEOUT", "8"))


def verify_external(method: str, config: dict, email: str, password: str) -> bool:
    if not password or not email:
        return False
    if method == "imap":
        return _imap_verify(config, email, password)
    if method == "ldap":
        return _ldap_verify(config, email, password)
    return False


def _fmt(tpl: str, email: str) -> str:
    return tpl.format(email=email, local=email.split("@", 1)[0])


def _imap_verify(config: dict, email: str, password: str) -> bool:
    host = config.get("host")
    if not host:
        return False
    port = int(config.get("port", 993))
    use_ssl = config.get("ssl", True)
    login = _fmt(config.get("login_format", "{email}"), email)
    M = None
    try:
        M = (imaplib.IMAP4_SSL(host, port, timeout=_TIMEOUT) if use_ssl
             else imaplib.IMAP4(host, port, timeout=_TIMEOUT))
        M.login(login, password)
        return True
    except Exception:  # noqa: BLE001  登入失敗一律視為驗證不通過
        return False
    finally:
        if M is not None:
            try:
                M.logout()
            except Exception:  # noqa: BLE001
                pass


def _ldap_verify(config: dict, email: str, password: str) -> bool:
    try:
        from ldap3 import ALL, Connection, Server
    except ImportError as e:  # 沒裝 ldap3 → 明確報錯，不要靜默當成密碼錯
        raise RuntimeError("LDAP 登入需要 ldap3 套件（pip install ldap3）") from e
    url = config.get("url")
    if not url:
        return False
    user = _fmt(config.get("user_template", "{email}"), email)
    conn = None
    try:
        server = Server(url, get_info=ALL, use_ssl=config.get("ssl", False), connect_timeout=_TIMEOUT)
        conn = Connection(server, user=user, password=password, receive_timeout=_TIMEOUT, auto_bind=True)
        return bool(conn.bound)
    except Exception:  # noqa: BLE001
        return False
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:  # noqa: BLE001
                pass
