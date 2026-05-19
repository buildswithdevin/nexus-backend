import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Text, Boolean, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column
from database.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Site(Base):
    __tablename__ = "sites"

    id:             Mapped[str]            = mapped_column(String,        primary_key=True, default=new_id)
    title:          Mapped[str]            = mapped_column(String(512),   nullable=False)
    url:            Mapped[str]            = mapped_column(String(2048),  nullable=False, unique=True, index=True)
    description:    Mapped[Optional[str]]  = mapped_column(Text)
    summary:        Mapped[Optional[str]]  = mapped_column(Text)
    favicon_url:    Mapped[Optional[str]]  = mapped_column(String(2048))
    raw_content:    Mapped[Optional[str]]  = mapped_column(Text)
    category:       Mapped[Optional[str]]  = mapped_column(String(128))
    tags:           Mapped[Optional[list]] = mapped_column(JSON, default=list)
    technologies:   Mapped[Optional[list]] = mapped_column(JSON, default=list)
    topics:         Mapped[Optional[list]] = mapped_column(JSON, default=list)
    notes:             Mapped[Optional[str]]  = mapped_column(Text)
    pinned:            Mapped[bool]           = mapped_column(Boolean, default=False)
    use_case:          Mapped[Optional[str]]  = mapped_column(Text)
    learning_value:    Mapped[Optional[str]]  = mapped_column(String(32))
    chroma_id:         Mapped[Optional[str]]  = mapped_column(String(128))
    restricted:        Mapped[bool]           = mapped_column(Boolean, default=False)
    restricted_reason: Mapped[Optional[str]]  = mapped_column(String(128))
    created_at:        Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at:        Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "title":          self.title,
            "url":            self.url,
            "description":    self.description,
            "summary":        self.summary,
            "favicon_url":    self.favicon_url,
            "category":       self.category,
            "tags":           self.tags or [],
            "technologies":   self.technologies or [],
            "topics":         self.topics or [],
            "notes":          self.notes,
            "pinned":            self.pinned,
            "use_case":          self.use_case,
            "learning_value":    self.learning_value,
            "restricted":        bool(self.restricted),
            "restricted_reason": self.restricted_reason,
            "created_at":        self.created_at.isoformat() if self.created_at else None,
            "updated_at":        self.updated_at.isoformat() if self.updated_at else None,
        }


class UserProfile(Base):
    __tablename__ = "user_profile"

    id:                  Mapped[str]            = mapped_column(String, primary_key=True, default=lambda: "default")
    liked_tags:          Mapped[Optional[dict]] = mapped_column(JSON, default=dict)    # {tag: weight}
    disliked_tags:       Mapped[Optional[dict]] = mapped_column(JSON, default=dict)    # {tag: weight}
    liked_categories:    Mapped[Optional[dict]] = mapped_column(JSON, default=dict)    # {cat: weight}
    disliked_categories: Mapped[Optional[dict]] = mapped_column(JSON, default=dict)    # {cat: weight}
    saved_topics:        Mapped[Optional[list]] = mapped_column(JSON, default=list)    # [topic str]
    dismissed_topics:    Mapped[Optional[list]] = mapped_column(JSON, default=list)    # [topic str]
    recent_queries:      Mapped[Optional[list]] = mapped_column(JSON, default=list)    # [{query,keywords,tags,categories,timestamp}]
    updated_at:          Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "liked_tags":          self.liked_tags or {},
            "disliked_tags":       self.disliked_tags or {},
            "liked_categories":    self.liked_categories or {},
            "disliked_categories": self.disliked_categories or {},
            "saved_topics":        self.saved_topics or [],
            "dismissed_topics":    self.dismissed_topics or [],
            "recent_queries":      self.recent_queries or [],
            "updated_at":          self.updated_at.isoformat() if self.updated_at else None,
        }


class Cluster(Base):
    __tablename__ = "clusters"

    id:            Mapped[str]            = mapped_column(String,       primary_key=True, default=new_id)
    name:          Mapped[str]            = mapped_column(String(256),  nullable=False)
    description:   Mapped[Optional[str]]  = mapped_column(Text)
    color:         Mapped[Optional[str]]  = mapped_column(String(16))
    site_ids:      Mapped[Optional[list]] = mapped_column(JSON, default=list)
    learning_path: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    insight:       Mapped[Optional[str]]  = mapped_column(Text)
    created_at:    Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "name":          self.name,
            "description":   self.description,
            "color":         self.color,
            "site_ids":      self.site_ids or [],
            "learning_path": self.learning_path or [],
            "insight":       self.insight,
            "created_at":    self.created_at.isoformat() if self.created_at else None,
        }
