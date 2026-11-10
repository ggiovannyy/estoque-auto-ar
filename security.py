"""Regras de seguranca que nao dependem do Flask: senha, tentativas de login e CSV."""
import hashlib
import threading
import time

MIN_PASSWORD = 8


def password_error(pw):
    """Mensagem de erro se a senha for fraca demais; None se estiver ok."""
    if len(pw or "") < MIN_PASSWORD:
        return f"A senha precisa ter pelo menos {MIN_PASSWORD} caracteres."
    return None


def password_mark(password_hash):
    """Marca da senha guardada no cookie de login: trocar a senha invalida as sessoes abertas com a antiga."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


class LoginThrottle:
    """Bloqueia uma chave (IP, ou IP + usuario) depois de erros de senha seguidos.

    Guarda tudo em memoria: reiniciar o sistema zera os bloqueios, o que basta
    para uma oficina com um unico servidor.
    """
    WINDOW_SECONDS = 15 * 60  # erros mais antigos que isso nao contam
    LOCK_SECONDS = 5 * 60

    def __init__(self, max_failures):
        self.max_failures = max_failures
        self.clock = time.monotonic
        self._failures = {}      # chave -> horarios dos erros recentes
        self._locked_until = {}  # chave -> horario em que o bloqueio acaba
        self._lock = threading.Lock()

    def retry_after(self, key):
        """Segundos que faltam para liberar a chave (0 = liberada)."""
        with self._lock:
            return max(0, self._locked_until.get(key, 0) - self.clock())

    def failure(self, key):
        with self._lock:
            now = self.clock()
            recent = [t for t in self._failures.get(key, []) if now - t < self.WINDOW_SECONDS] + [now]
            if len(recent) >= self.max_failures:
                self._locked_until[key] = now + self.LOCK_SECONDS
                recent = []
            self._failures[key] = recent

    def success(self, key):
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self):
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Impede que o Excel execute como formula um texto digitado (ex.: '=HYPERLINK(...)')."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


# A interface so carrega os proprios arquivos, inclusive as fontes (static/fonts).
# Sem 'unsafe-inline': a tela nao usa style="..." nem <style> (testado em e2e/test_csp.py).
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
    "img-src 'self' data: blob:",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(self), microphone=(), geolocation=()",
}
