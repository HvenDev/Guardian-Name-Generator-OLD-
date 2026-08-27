import random
import string
import itertools
from typing import Generator, Set, Optional
from platforms.base import Platform


CHARSET_LETTERS = string.ascii_lowercase
CHARSET_LETTERS_NUMBERS = string.ascii_lowercase + string.digits
CHARSET_LETTERS_NUMBERS_UNDERSCORE = string.ascii_lowercase + string.digits + "_"
CHARSET_ALL = string.ascii_lowercase + string.digits + "_."


class UsernameGenerator:
    def __init__(self, platform: Platform, length: int, charset: str, amount: int):
        self.platform = platform
        self.length = length
        self.charset = charset
        self.amount = amount
        self._seen: Set[str] = set()

    def _is_valid(self, username: str) -> bool:
        return self.platform.validate_username(username)

    def _add_if_valid(self, username: str) -> Optional[str]:
        username = username.lower()
        if username not in self._seen and self._is_valid(username):
            self._seen.add(username)
            return username
        return None

    def generate_random(self) -> Generator[str, None, None]:
        count = 0
        max_attempts = self.amount * 5
        attempts = 0
        while count < self.amount and attempts < max_attempts:
            name = "".join(random.choices(self.charset, k=self.length))
            result = self._add_if_valid(name)
            if result:
                count += 1
                yield result
            attempts += 1

    def generate_sequential(self) -> Generator[str, None, None]:
        count = 0
        if len(self.charset) ** self.length > 1_000_000:
            return
        for combo in itertools.product(self.charset, repeat=self.length):
            name = "".join(combo)
            result = self._add_if_valid(name)
            if result:
                count += 1
                yield result
                if count >= self.amount:
                    break

    def generate_smart(self) -> Generator[str, None, None]:
        prefixes = ["", "its", "real", "the", "im", "x", "xx", "xxx"]
        suffixes = ["", "x", "xx", "xd", "99", "0", "1", "7", "420", "_"]
        leet_map = {"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7"}
        base_words = [
            "nova", "vex", "nory", "zori", "abqx", "lynx", "drift", "flux",
            "ember", "frost", "blaze", "storm", "glitch", "pixel", "cyber",
            "neon", "void", "echo", "rise", "zen", "vox", "hex", "arc",
            "bit", "ion", "jax", "max", "rex", "ace", "ace", "zen",
            "sky", "sun", "fox", "owl", "bee", "ram", "owl", "ape",
        ]
        count = 0
        seen = set()

        for word in base_words:
            if count >= self.amount:
                break
            for base in [word, word[::-1]]:
                for prefix in prefixes:
                    for suffix in suffixes:
                        if count >= self.amount:
                            break
                        candidate = f"{prefix}{base}{suffix}"[:self.length]
                        if len(candidate) == self.length:
                            result = self._add_if_valid(candidate)
                            if result and result not in seen:
                                seen.add(result)
                                count += 1
                                yield result
                if count >= self.amount:
                    break
                for original, replacement in leet_map.items():
                    if count >= self.amount:
                        break
                    leet_word = word.replace(original, replacement)
                    for prefix in prefixes:
                        for suffix in suffixes:
                            if count >= self.amount:
                                break
                            candidate = f"{prefix}{leet_word}{suffix}"[:self.length]
                            if len(candidate) == self.length:
                                result = self._add_if_valid(candidate)
                                if result and result not in seen:
                                    seen.add(result)
                                    count += 1
                                    yield result
                    if count >= self.amount:
                        break

        while count < self.amount:
            name = "".join(random.choices(self.charset, k=self.length))
            result = self._add_if_valid(name)
            if result and result not in seen:
                seen.add(result)
                count += 1
                yield result

    def generate_word_based(self, wordlist_path: Optional[str] = None) -> Generator[str, None, None]:
        count = 0
        words = ["nova", "vex", "lynx", "drift", "flux", "ember", "frost", "blaze",
                 "storm", "glitch", "pixel", "cyber", "neon", "void", "echo", "rise",
                 "zen", "vox", "hex", "arc", "bit", "ion", "jax", "max", "rex", "ace"]

        if wordlist_path:
            try:
                with open(wordlist_path, "r") as f:
                    words = [line.strip().lower() for line in f if line.strip()]
            except FileNotFoundError:
                pass

        suffixes = ["", "x", "99", "0", "1", "7", "_", "xd"]
        for word in words:
            if count >= self.amount:
                break
            word = word.lower()
            if len(word) <= self.length:
                result = self._add_if_valid(word)
                if result:
                    count += 1
                    yield result
            for suffix in suffixes:
                if count >= self.amount:
                    break
                candidate = f"{word}{suffix}"[:self.length]
                if len(candidate) == self.length:
                    result = self._add_if_valid(candidate)
                    if result:
                        count += 1
                        yield result

        while count < self.amount:
            name = "".join(random.choices(self.charset, k=self.length))
            result = self._add_if_valid(name)
            if result:
                count += 1
                yield result

    def generate(self, mode: str = "Smart", wordlist_path: Optional[str] = None) -> Generator[str, None, None]:
        if mode == "Random":
            return self.generate_random()
        elif mode == "Sequential":
            return self.generate_sequential()
        elif mode == "Word-based":
            return self.generate_word_based(wordlist_path)
        else:
            return self.generate_smart()
