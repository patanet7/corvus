"""Fake IMAP server for Yahoo Mail contract testing.

Speaks enough IMAP4 to handle: LOGIN, SELECT, SEARCH, FETCH, LOGOUT.
Uses a self-signed SSL cert for imaplib.IMAP4_SSL compatibility.
"""

import email.mime.text
import socket
import ssl
import subprocess
import tempfile
import threading

SAMPLE_MESSAGES = {
    b"1": {
        "subject": "Invoice from Vendor",
        "from": "billing@vendor.com",
        "to": "thomas@yahoo.com",
        "date": "Mon, 24 Feb 2026 09:00:00 -0500",
        "body": "Please find attached invoice #1234.",
    },
    b"2": {
        "subject": "Newsletter: Weekly Update",
        "from": "news@example.com",
        "to": "thomas@yahoo.com",
        "date": "Sun, 23 Feb 2026 07:00:00 -0500",
        "body": "This week's highlights include...",
    },
}


def _build_rfc822(msg_data: dict) -> bytes:
    """Build an RFC822 message from dict."""
    msg = email.mime.text.MIMEText(msg_data["body"])
    msg["Subject"] = msg_data["subject"]
    msg["From"] = msg_data["from"]
    msg["To"] = msg_data["to"]
    msg["Date"] = msg_data["date"]
    return msg.as_bytes()


def _generate_self_signed_cert(tmpdir: str) -> tuple[str, str]:
    """Generate self-signed cert for SSL. Returns (certfile, keyfile)."""
    cert_path = f"{tmpdir}/cert.pem"
    key_path = f"{tmpdir}/key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            key_path,
            "-out",
            cert_path,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    return cert_path, key_path


class FakeIMAPServer:
    """Minimal IMAP4 server for contract tests."""

    def __init__(self, host: str = "127.0.0.1"):
        self._host = host
        self._port = 0
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._tmpdir = tempfile.mkdtemp()

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> int:
        """Start the server. Returns the port number."""
        cert_path, key_path = _generate_self_signed_cert(self._tmpdir)

        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw_sock.bind((self._host, 0))
        self._port = raw_sock.getsockname()[1]
        raw_sock.listen(5)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        self._server_socket = ctx.wrap_socket(raw_sock, server_side=True)

        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self._port

    def stop(self) -> None:
        self._running = False
        if self._server_socket:
            self._server_socket.close()

    def _serve(self) -> None:
        while self._running:
            try:
                conn, _ = self._server_socket.accept()
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
            except (OSError, ssl.SSLError):
                break

    def _handle_client(self, conn: socket.socket) -> None:
        try:
            conn.sendall(b"* OK IMAP4rev1 Fake Yahoo IMAP ready\r\n")

            while True:
                data = conn.recv(4096)
                if not data:
                    break

                line = data.decode("utf-8", errors="replace").strip()
                parts = line.split(" ", 2)
                if len(parts) < 2:
                    continue

                tag = parts[0]
                cmd = parts[1].upper()

                if cmd == "LOGIN":
                    conn.sendall(f"{tag} OK LOGIN completed\r\n".encode())

                elif cmd == "SELECT":
                    count = len(SAMPLE_MESSAGES)
                    conn.sendall(
                        f"* {count} EXISTS\r\n"
                        f"* 0 RECENT\r\n"
                        f"* OK [UIDVALIDITY 1]\r\n"
                        f"{tag} OK [READ-WRITE] SELECT completed\r\n".encode()
                    )

                elif cmd == "SEARCH":
                    nums = " ".join(str(n) for n in range(1, len(SAMPLE_MESSAGES) + 1))
                    conn.sendall(f"* SEARCH {nums}\r\n{tag} OK SEARCH completed\r\n".encode())

                elif cmd == "FETCH":
                    fetch_args = parts[2] if len(parts) > 2 else ""
                    msg_num = fetch_args.split(" ")[0].encode()
                    if msg_num in SAMPLE_MESSAGES:
                        rfc822 = _build_rfc822(SAMPLE_MESSAGES[msg_num])
                        if "RFC822.HEADER" in fetch_args:
                            header_end = rfc822.index(b"\n\n") + 1
                            header_data = rfc822[:header_end]
                            conn.sendall(
                                f"* {msg_num.decode()} FETCH (RFC822.HEADER {{{len(header_data)}}}\r\n".encode()
                                + header_data
                                + f")\r\n{tag} OK FETCH completed\r\n".encode()
                            )
                        else:
                            conn.sendall(
                                f"* {msg_num.decode()} FETCH (RFC822 {{{len(rfc822)}}}\r\n".encode()
                                + rfc822
                                + f")\r\n{tag} OK FETCH completed\r\n".encode()
                            )
                    else:
                        conn.sendall(f"{tag} NO Message not found\r\n".encode())

                elif cmd == "LOGOUT":
                    conn.sendall(f"* BYE IMAP4rev1 Logging out\r\n{tag} OK LOGOUT completed\r\n".encode())
                    break

                elif cmd == "CAPABILITY":
                    conn.sendall(f"* CAPABILITY IMAP4rev1\r\n{tag} OK CAPABILITY completed\r\n".encode())

                else:
                    conn.sendall(f"{tag} BAD Unknown command\r\n".encode())

        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        finally:
            conn.close()
