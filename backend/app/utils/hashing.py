from passlib.context import CryptContext

# Use Argon2 exclusively
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto"
)

def hash_password(password: str) -> str:
    """
    Hash a password using Argon2 (strong, memory-hard algorithm).
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its Argon2 hash.
    """
    return pwd_context.verify(plain_password, hashed_password)
