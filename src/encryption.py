"""
Encryption utilities for securing sensitive data like Plex tokens.
Uses Fernet symmetric encryption from the cryptography library.
"""

import os
from cryptography.fernet import Fernet


class TokenEncryption:
    """Handles encryption and decryption of sensitive tokens."""
    
    def __init__(self):
        """Initialize encryption with key from environment variable."""
        encryption_key = os.getenv("ENCRYPTION_KEY")
        if not encryption_key:
            raise ValueError("ENCRYPTION_KEY environment variable not set")
        
        # Convert string key to bytes
        self.cipher = Fernet(encryption_key.encode() if isinstance(encryption_key, str) else encryption_key)
    
    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string.
        
        Args:
            plaintext: The string to encrypt (e.g., Plex token)
            
        Returns:
            Encrypted string (base64 encoded)
        """
        if not plaintext:
            return ""
        
        encrypted_bytes = self.cipher.encrypt(plaintext.encode())
        return encrypted_bytes.decode()
    
    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt an encrypted string.
        
        Args:
            ciphertext: The encrypted string to decrypt
            
        Returns:
            Decrypted plaintext string
        """
        if not ciphertext:
            return ""
        
        decrypted_bytes = self.cipher.decrypt(ciphertext.encode())
        return decrypted_bytes.decode()


# Global instance for use throughout the application
def get_encryption() -> TokenEncryption:
    """Get or create global encryption instance."""
    return TokenEncryption()
