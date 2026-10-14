"""Solo los campos de Telegram que el bot usa. El resto se ignora."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class User(_Base):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None

    @property
    def nombre(self) -> str:
        partes = [self.first_name or "", self.last_name or ""]
        return " ".join(p for p in partes if p).strip() or (self.username or "")


class Chat(_Base):
    id: int
    type: str = "private"


class PhotoSize(_Base):
    file_id: str
    file_unique_id: str
    width: int = 0
    height: int = 0
    file_size: int | None = None


class Document(_Base):
    file_id: str
    file_unique_id: str
    file_name: str | None = None
    mime_type: str | None = None
    file_size: int | None = None


class Message(_Base):
    message_id: int
    chat: Chat
    from_: User | None = Field(default=None, alias="from")
    text: str | None = None
    caption: str | None = None
    photo: list[PhotoSize] | None = None
    document: Document | None = None
    media_group_id: str | None = None
    reply_to_message: Message | None = None


class CallbackQuery(_Base):
    id: str
    from_: User = Field(alias="from")
    message: Message | None = None
    data: str | None = None


class Update(_Base):
    update_id: int
    message: Message | None = None
    callback_query: CallbackQuery | None = None
