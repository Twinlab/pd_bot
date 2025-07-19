"""Пользовательские исключения для музыкального модуля V2."""


class MusicError(Exception):
    """Базовое исключение для всех ошибок музыкального модуля."""

    pass


class TrackError(MusicError):
    """Исключение, связанное с обработкой трека."""

    pass


class VoiceConnectionError(MusicError):
    """Исключение, связанное с подключением к голосовому каналу."""

    pass


class UserNotInVoiceChannel(MusicError):
    """Исключение, когда пользователь не находится в голосовом канале."""

    pass
