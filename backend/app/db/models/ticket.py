from sqlalchemy import Column, String
from app.db.base import Base, TimeStampedModel

class Ticket(TimeStampedModel):
    __tablename__ = "tickets"
    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
