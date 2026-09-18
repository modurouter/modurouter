class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 422, retryable: bool = False):
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable
        super().__init__(code)

    def payload(self, run_id: str | None = None):
        return {"code": self.code, "message": self.message, "retryable": self.retryable, "run_id": run_id}
