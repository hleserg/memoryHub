"""
File-based адаптер для Factual Memory.

Использует JSONL (JSON Lines) формат для хранения фактов в файле.
Подходит для локального запуска без внешних зависимостей.
"""

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import fcntl

from atman.core.models import FactRecord, Relation
from atman.core.ports import FactualMemory


class FileBackend(FactualMemory):
    """
    File-based реализация FactualMemory с использованием JSONL.
    
    Каждый факт сохраняется как отдельная JSON-строка в файле.
    При запуске все факты загружаются в память для быстрого доступа.
    """
    
    def __init__(self, filepath: str | Path):
        """
        Инициализирует file backend.
        
        Args:
            filepath: Путь к JSONL файлу для хранения фактов
        """
        self.filepath = Path(filepath)
        self._lockpath = self.filepath.with_name(f".{self.filepath.name}.lock")
        self._facts: dict[UUID, FactRecord] = {}
        self._load_facts()
    
    def _load_facts(self):
        """Загружает факты из файла в память."""
        self._facts = self._read_facts_from_disk()
    
    def _read_facts_from_disk(self) -> dict[UUID, FactRecord]:
        """Читает актуальные факты с диска без изменения состояния backend."""
        if not self.filepath.exists():
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
            return {}
        
        facts: dict[UUID, FactRecord] = {}
        with open(self.filepath, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    fact = FactRecord.model_validate(data)
                    facts[fact.id] = fact
        
        return facts
    
    @contextmanager
    def _storage_lock(self):
        """Сериализует операции read-modify-write между экземплярами FileBackend."""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lockpath, 'a', encoding='utf-8') as lock_file:
            self._lockpath.chmod(0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    
    def _save_facts(self, facts: dict[UUID, FactRecord] | None = None):
        """Сохраняет все факты в файл атомарной заменой."""
        facts_to_save = facts if facts is not None else self._facts
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        file_mode = self.filepath.stat().st_mode & 0o777 if self.filepath.exists() else 0o600
        temp_file = tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=self.filepath.parent,
            prefix=f".{self.filepath.name}.",
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(temp_file.name)
        
        try:
            with temp_file as f:
                for fact in facts_to_save.values():
                    json_line = fact.model_dump_json()
                    f.write(json_line + '\n')
                f.flush()
                os.fsync(f.fileno())
            
            temp_path.chmod(file_mode)
            temp_path.replace(self.filepath)
        finally:
            if temp_path.exists():
                temp_path.unlink()
    
    def add_fact(self, record: FactRecord) -> FactRecord:
        """Добавляет факт и сохраняет в файл."""
        fact_copy = record.model_copy(deep=True)
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            updated_facts[fact_copy.id] = fact_copy
            self._save_facts(updated_facts)
            self._facts = updated_facts
        return fact_copy.model_copy(deep=True)
    
    def get_fact(self, fact_id: UUID) -> FactRecord | None:
        """Получает факт по ID."""
        fact = self._facts.get(fact_id)
        return fact.model_copy(deep=True) if fact else None
    
    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10
    ) -> list[FactRecord]:
        """Ищет факты по запросу и тегам."""
        results = []
        
        normalized_query = query.lower() if query else None
        normalized_tags = [t.lower() for t in tags] if tags else None
        
        for fact in self._facts.values():
            if normalized_query and normalized_query not in fact.content.lower():
                continue
            
            if normalized_tags:
                fact_tags_lower = [t.lower() for t in fact.tags]
                if not all(tag in fact_tags_lower for tag in normalized_tags):
                    continue
            
            results.append(fact.model_copy(deep=True))
            
            if len(results) >= limit:
                break
        
        return results
    
    def link(self, source_id: UUID, target_id: UUID, relation_type: str) -> bool:
        """Создает связь между фактами и сохраняет в файл."""
        with self._storage_lock():
            updated_facts = self._read_facts_from_disk()
            source_fact = updated_facts.get(source_id)
            target_fact = updated_facts.get(target_id)
            
            if not source_fact or not target_fact:
                self._facts = updated_facts
                return False
            
            relation = Relation(
                target_id=target_id,
                relation_type=relation_type.strip().lower()
            )
            
            updated_source = source_fact.model_copy(deep=True)
            updated_source.relations.append(relation)
            updated_facts[source_id] = updated_source
            
            self._save_facts(updated_facts)
            self._facts = updated_facts
        return True
    
    def list_recent(self, limit: int = 10) -> list[FactRecord]:
        """Возвращает последние факты."""
        sorted_facts = sorted(
            self._facts.values(),
            key=lambda f: f.created_at,
            reverse=True
        )
        
        return [f.model_copy(deep=True) for f in sorted_facts[:limit]]
    
    def count(self) -> int:
        """Возвращает количество фактов."""
        return len(self._facts)
