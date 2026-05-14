"""
Exceptions for reflection adapters.
"""


class OllamaReflectionError(RuntimeError):
    """
    Error raised when Ollama reflection model fails after retries.

    Carries diagnostic information about the failed attempts.
    """

    def __init__(self, attempts: int, last_raw: str) -> None:
        """
        Initialize OllamaReflectionError.

        Args:
            attempts: Number of attempts made before failure
            last_raw: Raw response content from the last failed attempt (limited to 1KB)
        """
        self.attempts = attempts
        self.last_raw = last_raw[:1000]  # Limit to 1KB to prevent memory leaks
        super().__init__(
            f"Ollama reflection failed after {attempts} attempts. Last raw: {self.last_raw[:100]}"
        )


# Alias for OpenAI-compatible adapters (same error class, more generic name)
OpenAIReflectionError = OllamaReflectionError
