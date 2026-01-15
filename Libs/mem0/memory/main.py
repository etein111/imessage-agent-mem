import asyncio
import concurrent
import gc
import hashlib
import json
import logging
import os
import uuid
import warnings
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple
from dataclasses import dataclass
import pytz
from pydantic import ValidationError
from mem0.memory.time_metadata_builder import enrich_mem0_payload_time
from mem0.configs.base import MemoryConfig, MemoryItem
from mem0.configs.enums import MemoryType
from mem0.configs.prompts import (
    PROCEDURAL_MEMORY_SYSTEM_PROMPT,
    get_update_memory_messages,
    USER_PROFILE_MEMORY_EXTRACTION_PROMPT, USER_EPISODIC_MEMORY_EXTRACTION_PROMPT,
    USER_WORKING_SESSION_MEMORY_EXTRACTION_PROMPT, FALLBACK_PROFILE_MEMORY_CLASSIFIER_PROMPT,
    FALLBACK_EPISODIC_MEMORY_CLASSIFIER_PROMPT, USER_PROFILE_MEMORY_UPDATE_PROMPT, USER_EPISODIC_MEMORY_UPDATE_PROMPT,
    VECTOR_SEARCH_DECISION_PROMPT,REDIS_LAYER_FILTER_PROMPT,
)
from mem0.exceptions import ValidationError as Mem0ValidationError
from mem0.memory.base import MemoryBase
from mem0.memory.setup import mem0_dir, setup_config
from mem0.memory.storage import SQLiteManager
from mem0.memory.telemetry import capture_event
from mem0.memory.utils import (
    extract_json,
    get_fact_retrieval_messages,
    parse_messages,
    parse_vision_messages,
    process_telemetry_filters,
    remove_code_blocks,
)
from mem0.utils.factory import (
    EmbedderFactory,
    GraphStoreFactory,
    LlmFactory,
    VectorStoreFactory,
    RerankerFactory,
)

REDIS_STORE_AVAILABLE = False
redis_store = None
try:
    import sys
    import os

    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
    src_path = os.path.join(project_root, "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    from app.memory.redis_store import redis_store

    REDIS_STORE_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    REDIS_STORE_AVAILABLE = False
    redis_store = None


@dataclass
class ExtractionResult:
    mem_type: str  # "profile" | "episodic" | "working"
    fact_texts: List[str]
    meta_by_text: Dict[str, Dict[str, Any]]  # mem_category/mem_type/time...


@dataclass
class SearchPack:
    mem_type: str
    fact_texts: List[str]
    new_message_embeddings: Dict[str, Any]  # fact_text -> embedding
    retrieved_old_memory: List[Dict[str, str]]  # [{"id": "<tmp_int>", "text": "..."}]
    temp_uuid_mapping: Dict[str, str]  # "<tmp_int>" -> "<real_uuid>"


@dataclass
class MultiSearchResult:
    per_type_searchpack: Dict[str, "SearchPack"]  # mem_type -> pack


# 哪些 mem_type 允许 time 字段
MEM_TYPE_ALLOW_TIME = {
    "profile": False,
    "episodic": True,
    "working": True,
}

# Suppress SWIG deprecation warnings globally
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*SwigPy.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*swigvarlink.*")

# Initialize logger early for util functions
logger = logging.getLogger(__name__)


def _safe_deepcopy_config(config):
    """Safely deepcopy config, falling back to JSON serialization for non-serializable objects."""
    try:
        return deepcopy(config)
    except Exception as e:
        logger.debug(f"Deepcopy failed, using JSON serialization: {e}")

        config_class = type(config)

        if hasattr(config, "model_dump"):
            try:
                clone_dict = config.model_dump(mode="json")
            except Exception:
                clone_dict = {k: v for k, v in config.__dict__.items()}
        elif hasattr(config, "__dataclass_fields__"):
            from dataclasses import asdict
            clone_dict = asdict(config)
        else:
            clone_dict = {k: v for k, v in config.__dict__.items()}

        sensitive_tokens = ("auth", "credential", "password", "token", "secret", "key", "connection_class")
        for field_name in list(clone_dict.keys()):
            if any(token in field_name.lower() for token in sensitive_tokens):
                clone_dict[field_name] = None

        try:
            return config_class(**clone_dict)
        except Exception as reconstruction_error:
            logger.warning(
                f"Failed to reconstruct config: {reconstruction_error}. "
                f"Telemetry may be affected."
            )
            raise


def _build_filters_and_metadata(
        *,  # Enforce keyword-only arguments
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        run_id: Optional[str] = None,
        actor_id: Optional[str] = None,  # For query-time filtering
        input_metadata: Optional[Dict[str, Any]] = None,
        input_filters: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Constructs metadata for storage and filters for querying based on session and actor identifiers.

    This helper supports multiple session identifiers (`user_id`, `agent_id`, and/or `run_id`)
    for flexible session scoping and optionally narrows queries to a specific `actor_id`. It returns two dicts:

    1. `base_metadata_template`: Used as a template for metadata when storing new memories.
       It includes all provided session identifier(s) and any `input_metadata`.
    2. `effective_query_filters`: Used for querying existing memories. It includes all
       provided session identifier(s), any `input_filters`, and a resolved actor
       identifier for targeted filtering if specified by any actor-related inputs.

    Actor filtering precedence: explicit `actor_id` arg → `filters["actor_id"]`
    This resolved actor ID is used for querying but is not added to `base_metadata_template`,
    as the actor for storage is typically derived from message content at a later stage.

    Args:
        user_id (Optional[str]): User identifier, for session scoping.
        agent_id (Optional[str]): Agent identifier, for session scoping.
        run_id (Optional[str]): Run identifier, for session scoping.
        actor_id (Optional[str]): Explicit actor identifier, used as a potential source for
            actor-specific filtering. See actor resolution precedence in the main description.
        input_metadata (Optional[Dict[str, Any]]): Base dictionary to be augmented with
            session identifiers for the storage metadata template. Defaults to an empty dict.
        input_filters (Optional[Dict[str, Any]]): Base dictionary to be augmented with
            session and actor identifiers for query filters. Defaults to an empty dict.

    Returns:
        tuple[Dict[str, Any], Dict[str, Any]]: A tuple containing:
            - base_metadata_template (Dict[str, Any]): Metadata template for storing memories,
              scoped to the provided session(s).
            - effective_query_filters (Dict[str, Any]): Filters for querying memories,
              scoped to the provided session(s) and potentially a resolved actor.
    """

    base_metadata_template = deepcopy(input_metadata) if input_metadata else {}
    effective_query_filters = deepcopy(input_filters) if input_filters else {}

    # ---------- add all provided session ids ----------
    session_ids_provided = []

    if user_id:
        base_metadata_template["user_id"] = user_id
        effective_query_filters["user_id"] = user_id
        session_ids_provided.append("user_id")

    if agent_id:
        base_metadata_template["agent_id"] = agent_id
        effective_query_filters["agent_id"] = agent_id
        session_ids_provided.append("agent_id")

    if run_id:
        base_metadata_template["run_id"] = run_id
        effective_query_filters["run_id"] = run_id
        session_ids_provided.append("run_id")

    if not session_ids_provided:
        raise Mem0ValidationError(
            message="At least one of 'user_id', 'agent_id', or 'run_id' must be provided.",
            error_code="VALIDATION_001",
            details={"provided_ids": {"user_id": user_id, "agent_id": agent_id, "run_id": run_id}},
            suggestion="Please provide at least one identifier to scope the memory operation."
        )

    # ---------- optional actor filter ----------
    resolved_actor_id = actor_id or effective_query_filters.get("actor_id")
    if resolved_actor_id:
        effective_query_filters["actor_id"] = resolved_actor_id

    return base_metadata_template, effective_query_filters


setup_config()
logger = logging.getLogger(__name__)


class Memory(MemoryBase):
    def __init__(self, config: MemoryConfig = MemoryConfig()):
        self.config = config

        self.custom_fact_extraction_prompt = self.config.custom_fact_extraction_prompt
        self.custom_update_memory_prompt = self.config.custom_update_memory_prompt
        self.embedding_model = EmbedderFactory.create(
            self.config.embedder.provider,
            self.config.embedder.config,
            self.config.vector_store.config,
        )
        self.vector_store = VectorStoreFactory.create(
            self.config.vector_store.provider, self.config.vector_store.config
        )
        self.llm = LlmFactory.create(self.config.llm.provider, self.config.llm.config)
        self.db = SQLiteManager(self.config.history_db_path)
        self.collection_name = self.config.vector_store.config.collection_name
        self.api_version = self.config.version

        # Initialize reranker if configured
        self.reranker = None
        if config.reranker:
            self.reranker = RerankerFactory.create(
                config.reranker.provider,
                config.reranker.config
            )

        self.enable_graph = False

        if self.config.graph_store.config:
            provider = self.config.graph_store.provider
            self.graph = GraphStoreFactory.create(provider, self.config)
            self.enable_graph = True
        else:
            self.graph = None
        # Create telemetry config manually to avoid deepcopy issues with thread locks
        telemetry_config_dict = {}
        if hasattr(self.config.vector_store.config, 'model_dump'):
            # For pydantic models
            telemetry_config_dict = self.config.vector_store.config.model_dump()
        else:
            # For other objects, manually copy common attributes
            for attr in ['host', 'port', 'path', 'api_key', 'index_name', 'dimension', 'metric']:
                if hasattr(self.config.vector_store.config, attr):
                    telemetry_config_dict[attr] = getattr(self.config.vector_store.config, attr)

        # Override collection name for telemetry
        telemetry_config_dict['collection_name'] = "mem0migrations"

        # Set path for file-based vector stores
        telemetry_config = _safe_deepcopy_config(self.config.vector_store.config)
        if self.config.vector_store.provider in ["faiss", "qdrant"]:
            provider_path = f"migrations_{self.config.vector_store.provider}"
            telemetry_config_dict['path'] = os.path.join(mem0_dir, provider_path)
            os.makedirs(telemetry_config_dict['path'], exist_ok=True)

        # Create the config object using the same class as the original
        telemetry_config = self.config.vector_store.config.__class__(**telemetry_config_dict)
        self._telemetry_vector_store = VectorStoreFactory.create(
            self.config.vector_store.provider, telemetry_config
        )
        capture_event("mem0.init", self, {"sync_type": "sync"})

    @classmethod
    def from_config(cls, config_dict: Dict[str, Any]):
        try:
            config = cls._process_config(config_dict)
            config = MemoryConfig(**config_dict)
        except ValidationError as e:
            logger.error(f"Configuration validation error: {e}")
            raise
        return cls(config)

    @staticmethod
    def _process_config(config_dict: Dict[str, Any]) -> Dict[str, Any]:
        if "graph_store" in config_dict:
            if "vector_store" not in config_dict and "embedder" in config_dict:
                config_dict["vector_store"] = {}
                config_dict["vector_store"]["config"] = {}
                config_dict["vector_store"]["config"]["embedding_model_dims"] = config_dict["embedder"]["config"][
                    "embedding_dims"
                ]
        try:
            return config_dict
        except ValidationError as e:
            logger.error(f"Configuration validation error: {e}")
            raise

    def _fallback_classify_memories(self, texts: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Batch classify action_texts that failed exact match with extracted facts.
        Returns: {text -> extra_meta_dict}
        """
        if not texts:
            return {}

        # 去重但保持文本一致性
        uniq = []
        seen = set()
        for t in texts:
            t = (t or "").strip()
            if t and t not in seen:
                seen.add(t)
                uniq.append(t)

        payload = {"items": uniq}

        try:
            resp = self.llm.generate_response(
                messages=[
                    {"role": "system", "content": FALLBACK_MEMORY_CLASSIFIER_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
            )
            resp = remove_code_blocks(resp)

            try:
                obj = json.loads(resp)
            except json.JSONDecodeError:
                obj = json.loads(extract_json(resp))

            items = obj.get("items", [])
            out: Dict[str, Dict[str, Any]] = {}

            for it in items:
                if not isinstance(it, dict):
                    continue
                text = (it.get("text") or "").strip()
                if not text:
                    continue

                out[text] = {
                    "fact_schema_version": "v2_fallback_classifier",
                    "mem_category": it.get("mem_category"),
                    "mem_type": it.get("mem_type"),
                    "entities": it.get("entities", []) if isinstance(it.get("entities"), list) else [],
                    "time": it.get("time"),
                    "sentiment": it.get("sentiment"),
                    "emotion": it.get("emotion"),
                    "confidence": it.get("confidence"),
                    "sensitivity": it.get("sensitivity"),
                }

            return out

        except Exception as e:
            logger.error(f"Fallback classifier failed: {e}")
            return {}

    def _should_use_agent_memory_extraction(self, messages, metadata):
        """Determine whether to use agent memory extraction based on the logic:
        - If agent_id is present and messages contain assistant role -> True
        - Otherwise -> False

        Args:
            messages: List of message dictionaries
            metadata: Metadata containing user_id, agent_id, etc.

        Returns:
            bool: True if should use agent memory extraction, False for user memory extraction
        """
        # Check if agent_id is present in metadata
        has_agent_id = metadata.get("agent_id") is not None

        # Check if there are assistant role messages
        has_assistant_messages = any(msg.get("role") == "assistant" for msg in messages)

        # Use agent memory extraction if agent_id is present and there are assistant messages
        return has_agent_id and has_assistant_messages

    def add(
            self,
            messages,
            *,
            user_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            run_id: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            infer: bool = True,
            memory_type: Optional[str] = None,
            prompt: Optional[str] = None,
    ):
        """
        Create a new memory.

        Adds new memories scoped to a single session id (e.g. `user_id`, `agent_id`, or `run_id`). One of those ids is required.

        Args:
            messages (str or List[Dict[str, str]]): The message content or list of messages
                (e.g., `[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]`)
                to be processed and stored.
            user_id (str, optional): ID of the user creating the memory. Defaults to None.
            agent_id (str, optional): ID of the agent creating the memory. Defaults to None.
            run_id (str, optional): ID of the run creating the memory. Defaults to None.
            metadata (dict, optional): Metadata to store with the memory. Defaults to None.
            infer (bool, optional): If True (default), an LLM is used to extract key facts from
                'messages' and decide whether to add, update, or delete related memories.
                If False, 'messages' are added as raw memories directly.
            memory_type (str, optional): Specifies the type of memory. Currently, only
                `MemoryType.PROCEDURAL.value` ("procedural_memory") is explicitly handled for
                creating procedural memories (typically requires 'agent_id'). Otherwise, memories
                are treated as general conversational/factual memories.memory_type (str, optional): Type of memory to create. Defaults to None. By default, it creates the short term memories and long term (semantic and episodic) memories. Pass "procedural_memory" to create procedural memories.
            prompt (str, optional): Prompt to use for the memory creation. Defaults to None.


        Returns:
            dict: A dictionary containing the result of the memory addition operation, typically
                  including a list of memory items affected (added, updated) under a "results" key,
                  and potentially "relations" if graph store is enabled.
                  Example for v1.1+: `{"results": [{"id": "...", "memory": "...", "event": "ADD"}]}`

        Raises:
            Mem0ValidationError: If input validation fails (invalid memory_type, messages format, etc.).
            VectorStoreError: If vector store operations fail.
            GraphStoreError: If graph store operations fail.
            EmbeddingError: If embedding generation fails.
            LLMError: If LLM operations fail.
            DatabaseError: If database operations fail.
        """

        processed_metadata, effective_filters = _build_filters_and_metadata(
            user_id=user_id,
            agent_id=agent_id,
            run_id=run_id,
            input_metadata=metadata,
        )

        if memory_type is not None and memory_type != MemoryType.PROCEDURAL.value:
            raise Mem0ValidationError(
                message=f"Invalid 'memory_type'. Please pass {MemoryType.PROCEDURAL.value} to create procedural memories.",
                error_code="VALIDATION_002",
                details={"provided_type": memory_type, "valid_type": MemoryType.PROCEDURAL.value},
                suggestion=f"Use '{MemoryType.PROCEDURAL.value}' to create procedural memories."
            )

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        elif isinstance(messages, dict):
            messages = [messages]

        elif not isinstance(messages, list):
            raise Mem0ValidationError(
                message="messages must be str, dict, or list[dict]",
                error_code="VALIDATION_003",
                details={"provided_type": type(messages).__name__, "valid_types": ["str", "dict", "list[dict]"]},
                suggestion="Convert your input to a string, dictionary, or list of dictionaries."
            )

        if agent_id is not None and memory_type == MemoryType.PROCEDURAL.value:
            results = self._create_procedural_memory(messages, metadata=processed_metadata, prompt=prompt)
            return results

        if self.config.llm.config.get("enable_vision"):
            messages = parse_vision_messages(messages, self.llm, self.config.llm.config.get("vision_details"))
        else:
            messages = parse_vision_messages(messages)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future1 = executor.submit(self._add_to_vector_store, messages, processed_metadata, effective_filters, infer)
            future2 = executor.submit(self._add_to_graph, messages, effective_filters)

            concurrent.futures.wait([future1, future2])

            vector_store_result = future1.result()
            graph_result = future2.result()

        if self.enable_graph:
            return {
                "results": vector_store_result,
                "relations": graph_result,
            }

        return {"results": vector_store_result}

    from typing import Any, Dict

    def _add_to_vector_store(self, messages, metadata, filters, infer):
        if not infer:
            returned_memories = []
            for message_dict in messages:
                if (
                        not isinstance(message_dict, dict)
                        or message_dict.get("role") is None
                        or message_dict.get("content") is None
                ):
                    logger.warning(f"Skipping invalid message format: {message_dict}")
                    continue

                if message_dict["role"] == "system":
                    continue

                per_msg_meta = deepcopy(metadata)
                per_msg_meta["role"] = message_dict["role"]

                actor_name = message_dict.get("name")
                if actor_name:
                    per_msg_meta["actor_id"] = actor_name

                msg_content = message_dict["content"]
                msg_embeddings = self.embedding_model.embed(msg_content, "add")
                mem_id = self._create_memory(msg_content, msg_embeddings, per_msg_meta)

                returned_memories.append(
                    {
                        "id": mem_id,
                        "memory": msg_content,
                        "event": "ADD",
                        "actor_id": actor_name if actor_name else None,
                        "role": message_dict["role"],
                    }
                )
            return returned_memories

        parsed_messages = parse_messages(messages)

        if self.config.custom_fact_extraction_prompt:
            system_prompt = self.config.custom_fact_extraction_prompt
            user_prompt = f"Input:\n{parsed_messages}"
        else:
            # Determine if this should use agent memory extraction based on agent_id presence
            # and role types in messages
            is_agent_memory = self._should_use_agent_memory_extraction(messages, metadata)
            system_prompt, user_prompt = get_fact_retrieval_messages(parsed_messages, is_agent_memory)

        response = self.llm.generate_response(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )

        # ------------------------------------------------------------
        # Parse facts (NEW: list[dict] with "text"+metadata) or (OLD: list[str])
        # Output:
        #   new_retrieved_facts_texts: List[str]  (always)
        #   fact_meta_by_text: Dict[text, Dict]  (only for NEW, else empty)
        # ------------------------------------------------------------
        new_retrieved_facts_texts: List[str] = []
        fact_meta_by_text: Dict[str, Dict[str, Any]] = {}

        try:
            response = remove_code_blocks(response)
            if not response.strip():
                parsed_obj = {"facts": []}
            else:
                try:
                    parsed_obj = json.loads(response)
                except json.JSONDecodeError:
                    extracted_json = extract_json(response)
                    parsed_obj = json.loads(extracted_json)

            facts = parsed_obj.get("facts", [])

            # NEW: structured facts list[dict]
            if isinstance(facts, list) and facts and isinstance(facts[0], dict):
                for f in facts:
                    if not isinstance(f, dict):
                        continue
                    text = (f.get("text") or "").strip()
                    if not text:
                        continue

                    new_retrieved_facts_texts.append(text)

                    # Store per-fact metadata (you can also nest these under "mem" if you prefer)
                    fact_meta_by_text[text] = {
                        "fact_schema_version": "v2_structured",

                        # core classification fields
                        "mem_category": f.get("mem_category"),
                        "mem_type": f.get("mem_type"),

                        # extraction fields
                        "entities": f.get("entities", []) if isinstance(f.get("entities"), list) else [],
                        "time": f.get("time"),  # object or None/null
                        "sentiment": f.get("sentiment"),
                        "emotion": f.get("emotion"),
                        "confidence": f.get("confidence"),
                        "sensitivity": f.get("sensitivity"),
                    }

            # OLD: list[str]
            elif isinstance(facts, list):
                new_retrieved_facts_texts = [str(x).strip() for x in facts if str(x).strip()]
                fact_meta_by_text = {}

            else:
                new_retrieved_facts_texts = []
                fact_meta_by_text = {}

        except Exception as e:
            logger.error(f"Error in parsing facts: {e}")
            new_retrieved_facts_texts = []
            fact_meta_by_text = {}

        if not new_retrieved_facts_texts:
            logger.debug("No new facts retrieved from input. Skipping memory update LLM call.")

        retrieved_old_memory = []
        new_message_embeddings = {}

        # Search for existing memories using the provided session identifiers
        search_filters = {}
        if filters.get("user_id"):
            search_filters["user_id"] = filters["user_id"]
        if filters.get("agent_id"):
            search_filters["agent_id"] = filters["agent_id"]
        if filters.get("run_id"):
            search_filters["run_id"] = filters["run_id"]

        for fact_text in new_retrieved_facts_texts:
            messages_embeddings = self.embedding_model.embed(fact_text, "add")
            new_message_embeddings[fact_text] = messages_embeddings
            existing_memories = self.vector_store.search(
                query=fact_text,
                vectors=messages_embeddings,
                limit=5,
                filters=search_filters,
            )
            for mem in existing_memories:
                retrieved_old_memory.append({"id": mem.id, "text": mem.payload.get("data", "")})

        unique_data = {}
        for item in retrieved_old_memory:
            unique_data[item["id"]] = item
        retrieved_old_memory = list(unique_data.values())
        logger.info(f"Total existing memories: {len(retrieved_old_memory)}")

        # mapping UUIDs with integers for handling UUID hallucinations
        temp_uuid_mapping = {}
        for idx, item in enumerate(retrieved_old_memory):
            temp_uuid_mapping[str(idx)] = item["id"]
            retrieved_old_memory[idx]["id"] = str(idx)

        if new_retrieved_facts_texts:
            function_calling_prompt = get_update_memory_messages(
                retrieved_old_memory, new_retrieved_facts_texts, self.config.custom_update_memory_prompt
            )

            try:
                response = self.llm.generate_response(
                    messages=[{"role": "user", "content": function_calling_prompt}],
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                logger.error(f"Error in new memory actions response: {e}")
                response = ""

            try:
                if not response or not response.strip():
                    logger.warning("Empty response from LLM, no memories to extract")
                    new_memories_with_actions = {}
                else:
                    response = remove_code_blocks(response)
                    new_memories_with_actions = json.loads(response)
            except Exception as e:
                logger.error(f"Invalid JSON response: {e}")
                new_memories_with_actions = {}
        else:
            new_memories_with_actions = {}
        # ------------------------------------------------------------
        # Fallback: batch classify action_texts that don't match extracted fact.text
        # ------------------------------------------------------------
        needs_fallback: List[str] = []
        for resp in new_memories_with_actions.get("memory", []):
            try:
                event_type = resp.get("event")
                if event_type not in ("ADD", "UPDATE"):
                    continue
                action_text = (resp.get("text") or "").strip()
                if not action_text:
                    continue
                if action_text not in fact_meta_by_text:
                    needs_fallback.append(action_text)
            except Exception:
                continue

        fallback_meta_by_text = self._fallback_classify_memories(needs_fallback) if needs_fallback else {}

        returned_memories = []
        try:
            for resp in new_memories_with_actions.get("memory", []):
                logger.info(resp)
                try:
                    action_text = (resp.get("text") or "").strip()
                    if not action_text:
                        logger.info("Skipping memory entry because of empty `text` field.")
                        continue

                    event_type = resp.get("event")

                    if event_type == "ADD":
                        # merge per-fact metadata if we can match it
                        per_meta = deepcopy(metadata)
                        extra_meta = fact_meta_by_text.get(action_text)
                        if not extra_meta:
                            extra_meta = fallback_meta_by_text.get(action_text)

                        if extra_meta:
                            per_meta.update(extra_meta)

                        memory_id = self._create_memory(
                            data=action_text,
                            existing_embeddings=new_message_embeddings,
                            metadata=per_meta,
                        )
                        returned_memories.append({"id": memory_id, "memory": action_text, "event": event_type})

                    elif event_type == "UPDATE":
                        per_meta = deepcopy(metadata)
                        extra_meta = fact_meta_by_text.get(action_text)
                        if not extra_meta:
                            extra_meta = fallback_meta_by_text.get(action_text)

                        if extra_meta:
                            per_meta.update(extra_meta)

                        self._update_memory(
                            memory_id=temp_uuid_mapping[resp.get("id")],
                            data=action_text,
                            existing_embeddings=new_message_embeddings,
                            metadata=per_meta,
                        )
                        returned_memories.append(
                            {
                                "id": temp_uuid_mapping[resp.get("id")],
                                "memory": action_text,
                                "event": event_type,
                                "previous_memory": resp.get("old_memory"),
                            }
                        )

                    elif event_type == "DELETE":
                        self._delete_memory(memory_id=temp_uuid_mapping[resp.get("id")])
                        returned_memories.append(
                            {
                                "id": temp_uuid_mapping[resp.get("id")],
                                "memory": action_text,
                                "event": event_type,
                            }
                        )

                    elif event_type == "NONE":
                        # Even if content doesn't need updating, update session IDs if provided
                        memory_id = temp_uuid_mapping.get(resp.get("id"))
                        if memory_id and (metadata.get("agent_id") or metadata.get("run_id")):
                            existing_memory = self.vector_store.get(vector_id=memory_id)
                            updated_metadata = deepcopy(existing_memory.payload)
                            if metadata.get("agent_id"):
                                updated_metadata["agent_id"] = metadata["agent_id"]
                            if metadata.get("run_id"):
                                updated_metadata["run_id"] = metadata["run_id"]
                            updated_metadata["updated_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()

                            self.vector_store.update(
                                vector_id=memory_id,
                                vector=None,  # Keep same embeddings
                                payload=updated_metadata,
                            )
                            logger.info(f"Updated session IDs for memory {memory_id}")
                        else:
                            logger.info("NOOP for Memory.")

                except Exception as e:
                    logger.error(f"Error processing memory action: {resp}, Error: {e}")

        except Exception as e:
            logger.error(f"Error iterating new_memories_with_actions: {e}")

        keys, encoded_ids = process_telemetry_filters(filters)
        capture_event(
            "mem0.add",
            self,
            {"version": self.api_version, "keys": keys, "encoded_ids": encoded_ids, "sync_type": "sync"},
        )
        return returned_memories

    def _add_to_graph(self, messages, filters):
        added_entities = []
        if self.enable_graph:
            if filters.get("user_id") is None:
                filters["user_id"] = "user"

            data = "\n".join([msg["content"] for msg in messages if "content" in msg and msg["role"] != "system"])
            added_entities = self.graph.add(data, filters)

        return added_entities

    def get(self, memory_id):
        """
        Retrieve a memory by ID.

        Args:
            memory_id (str): ID of the memory to retrieve.

        Returns:
            dict: Retrieved memory.
        """
        capture_event("mem0.get", self, {"memory_id": memory_id, "sync_type": "sync"})
        memory = self.vector_store.get(vector_id=memory_id)
        if not memory:
            return None

        promoted_payload_keys = [
            "user_id",
            "agent_id",
            "run_id",
            "actor_id",
            "role",
        ]

        core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", *promoted_payload_keys}

        result_item = MemoryItem(
            id=memory.id,
            memory=memory.payload.get("data", ""),
            hash=memory.payload.get("hash"),
            created_at=memory.payload.get("created_at"),
            updated_at=memory.payload.get("updated_at"),
        ).model_dump()

        for key in promoted_payload_keys:
            if key in memory.payload:
                result_item[key] = memory.payload[key]

        additional_metadata = {k: v for k, v in memory.payload.items() if k not in core_and_promoted_keys}
        if additional_metadata:
            result_item["metadata"] = additional_metadata

        return result_item

    def get_all(
            self,
            *,
            user_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            run_id: Optional[str] = None,
            filters: Optional[Dict[str, Any]] = None,
            limit: int = 100,
    ):
        """
        List all memories.

        Args:
            user_id (str, optional): user id
            agent_id (str, optional): agent id
            run_id (str, optional): run id
            filters (dict, optional): Additional custom key-value filters to apply to the search.
                These are merged with the ID-based scoping filters. For example,
                `filters={"actor_id": "some_user"}`.
            limit (int, optional): The maximum number of memories to return. Defaults to 100.

        Returns:
            dict: A dictionary containing a list of memories under the "results" key,
                  and potentially "relations" if graph store is enabled. For API v1.0,
                  it might return a direct list (see deprecation warning).
                  Example for v1.1+: `{"results": [{"id": "...", "memory": "...", ...}]}`
        """

        _, effective_filters = _build_filters_and_metadata(
            user_id=user_id, agent_id=agent_id, run_id=run_id, input_filters=filters
        )

        if not any(key in effective_filters for key in ("user_id", "agent_id", "run_id")):
            raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be specified.")

        keys, encoded_ids = process_telemetry_filters(effective_filters)
        capture_event(
            "mem0.get_all", self, {"limit": limit, "keys": keys, "encoded_ids": encoded_ids, "sync_type": "sync"}
        )

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_memories = executor.submit(self._get_all_from_vector_store, effective_filters, limit)
            future_graph_entities = (
                executor.submit(self.graph.get_all, effective_filters, limit) if self.enable_graph else None
            )

            concurrent.futures.wait(
                [future_memories, future_graph_entities] if future_graph_entities else [future_memories]
            )

            all_memories_result = future_memories.result()
            graph_entities_result = future_graph_entities.result() if future_graph_entities else None

        if self.enable_graph:
            return {"results": all_memories_result, "relations": graph_entities_result}

        return {"results": all_memories_result}

    def _get_all_from_vector_store(self, filters, limit):
        memories_result = self.vector_store.list(filters=filters, limit=limit)

        # Handle different vector store return formats by inspecting first element
        if isinstance(memories_result, (tuple, list)) and len(memories_result) > 0:
            first_element = memories_result[0]

            # If first element is a container, unwrap one level
            if isinstance(first_element, (list, tuple)):
                actual_memories = first_element
            else:
                # First element is a memory object, structure is already flat
                actual_memories = memories_result
        else:
            actual_memories = memories_result

        promoted_payload_keys = [
            "user_id",
            "agent_id",
            "run_id",
            "actor_id",
            "role",
        ]
        core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", *promoted_payload_keys}

        formatted_memories = []
        for mem in actual_memories:
            memory_item_dict = MemoryItem(
                id=mem.id,
                memory=mem.payload.get("data", ""),
                hash=mem.payload.get("hash"),
                created_at=mem.payload.get("created_at"),
                updated_at=mem.payload.get("updated_at"),
            ).model_dump(exclude={"score"})

            for key in promoted_payload_keys:
                if key in mem.payload:
                    memory_item_dict[key] = mem.payload[key]

            additional_metadata = {k: v for k, v in mem.payload.items() if k not in core_and_promoted_keys}
            if additional_metadata:
                memory_item_dict["metadata"] = additional_metadata

            formatted_memories.append(memory_item_dict)

        return formatted_memories

    def search(
            self,
            query: str,
            *,
            user_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            run_id: Optional[str] = None,
            limit: int = 100,
            filters: Optional[Dict[str, Any]] = None,
            threshold: Optional[float] = None,
            rerank: bool = True,
    ):
        """
        Searches for memories based on a query
        Args:
            query (str): Query to search for.
            user_id (str, optional): ID of the user to search for. Defaults to None.
            agent_id (str, optional): ID of the agent to search for. Defaults to None.
            run_id (str, optional): ID of the run to search for. Defaults to None.
            limit (int, optional): Limit the number of results. Defaults to 100.
            filters (dict, optional): Legacy filters to apply to the search. Defaults to None.
            threshold (float, optional): Minimum score for a memory to be included in the results. Defaults to None.
            filters (dict, optional): Enhanced metadata filtering with operators:
                - {"key": "value"} - exact match
                - {"key": {"eq": "value"}} - equals
                - {"key": {"ne": "value"}} - not equals
                - {"key": {"in": ["val1", "val2"]}} - in list
                - {"key": {"nin": ["val1", "val2"]}} - not in list
                - {"key": {"gt": 10}} - greater than
                - {"key": {"gte": 10}} - greater than or equal
                - {"key": {"lt": 10}} - less than
                - {"key": {"lte": 10}} - less than or equal
                - {"key": {"contains": "text"}} - contains text
                - {"key": {"icontains": "text"}} - case-insensitive contains
                - {"key": "*"} - wildcard match (any value)
                - {"AND": [filter1, filter2]} - logical AND
                - {"OR": [filter1, filter2]} - logical OR
                - {"NOT": [filter1]} - logical NOT

        Returns:
            dict: A dictionary containing the search results, typically under a "results" key,
                  and potentially "relations" if graph store is enabled.
                  Example for v1.1+: `{"results": [{"id": "...", "memory": "...", "score": 0.8, ...}]}`
        """
        _, effective_filters = _build_filters_and_metadata(
            user_id=user_id, agent_id=agent_id, run_id=run_id, input_filters=filters
        )

        if not any(key in effective_filters for key in ("user_id", "agent_id", "run_id")):
            raise ValueError("At least one of 'user_id', 'agent_id', or 'run_id' must be specified.")

        # Apply enhanced metadata filtering if advanced operators are detected
        if filters and self._has_advanced_operators(filters):
            processed_filters = self._process_metadata_filters(filters)
            effective_filters.update(processed_filters)
        elif filters:
            # Simple filters, merge directly
            effective_filters.update(filters)

        keys, encoded_ids = process_telemetry_filters(effective_filters)
        capture_event(
            "mem0.search",
            self,
            {
                "limit": limit,
                "version": self.api_version,
                "keys": keys,
                "encoded_ids": encoded_ids,
                "sync_type": "sync",
                "threshold": threshold,
                "advanced_filters": bool(filters and self._has_advanced_operators(filters)),
            },
        )

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_memories = executor.submit(self._search_vector_store, query, effective_filters, limit, threshold)
            future_graph_entities = (
                executor.submit(self.graph.search, query, effective_filters, limit) if self.enable_graph else None
            )

            concurrent.futures.wait(
                [future_memories, future_graph_entities] if future_graph_entities else [future_memories]
            )

            original_memories = future_memories.result()
            graph_entities = future_graph_entities.result() if future_graph_entities else None

        # Apply reranking if enabled and reranker is available
        # 仅当结果是列表时才进行重排；对于分层结构(dict) 的结果不做 rerank
        if rerank and self.reranker and isinstance(original_memories, list) and original_memories:
            try:
                reranked_memories = self.reranker.rerank(query, original_memories, limit)
                original_memories = reranked_memories
            except Exception as e:
                logger.warning(f"Reranking failed, using original results: {e}")

        if self.enable_graph:
            return {"results": original_memories, "relations": graph_entities}

        return {"results": original_memories}

    def _process_metadata_filters(self, metadata_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process enhanced metadata filters and convert them to vector store compatible format.

        Args:
            metadata_filters: Enhanced metadata filters with operators

        Returns:
            Dict of processed filters compatible with vector store
        """
        processed_filters = {}

        def process_condition(key: str, condition: Any) -> Dict[str, Any]:
            if not isinstance(condition, dict):
                # Simple equality: {"key": "value"}
                if condition == "*":
                    # Wildcard: match everything for this field (implementation depends on vector store)
                    return {key: "*"}
                return {key: condition}

            result = {}
            for operator, value in condition.items():
                # Map platform operators to universal format that can be translated by each vector store
                operator_map = {
                    "eq": "eq", "ne": "ne", "gt": "gt", "gte": "gte",
                    "lt": "lt", "lte": "lte", "in": "in", "nin": "nin",
                    "contains": "contains", "icontains": "icontains"
                }

                if operator in operator_map:
                    result[key] = {operator_map[operator]: value}
                else:
                    raise ValueError(f"Unsupported metadata filter operator: {operator}")
            return result

        for key, value in metadata_filters.items():
            if key == "AND":
                # Logical AND: combine multiple conditions
                if not isinstance(value, list):
                    raise ValueError("AND operator requires a list of conditions")
                for condition in value:
                    for sub_key, sub_value in condition.items():
                        processed_filters.update(process_condition(sub_key, sub_value))
            elif key == "OR":
                # Logical OR: Pass through to vector store for implementation-specific handling
                if not isinstance(value, list) or not value:
                    raise ValueError("OR operator requires a non-empty list of conditions")
                # Store OR conditions in a way that vector stores can interpret
                processed_filters["$or"] = []
                for condition in value:
                    or_condition = {}
                    for sub_key, sub_value in condition.items():
                        or_condition.update(process_condition(sub_key, sub_value))
                    processed_filters["$or"].append(or_condition)
            elif key == "NOT":
                # Logical NOT: Pass through to vector store for implementation-specific handling
                if not isinstance(value, list) or not value:
                    raise ValueError("NOT operator requires a non-empty list of conditions")
                processed_filters["$not"] = []
                for condition in value:
                    not_condition = {}
                    for sub_key, sub_value in condition.items():
                        not_condition.update(process_condition(sub_key, sub_value))
                    processed_filters["$not"].append(not_condition)
            else:
                processed_filters.update(process_condition(key, value))

        return processed_filters

    def _has_advanced_operators(self, filters: Dict[str, Any]) -> bool:
        """
        Check if filters contain advanced operators that need special processing.

        Args:
            filters: Dictionary of filters to check

        Returns:
            bool: True if advanced operators are detected
        """
        if not isinstance(filters, dict):
            return False

        for key, value in filters.items():
            # Check for platform-style logical operators
            if key in ["AND", "OR", "NOT"]:
                return True
            # Check for comparison operators (without $ prefix for universal compatibility)
            if isinstance(value, dict):
                for op in value.keys():
                    if op in ["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "icontains"]:
                        return True
            # Check for wildcard values
            if value == "*":
                return True
        return False

    def _search_vector_store(self, query, filters, limit, threshold: Optional[float] = None):
        """
        Vector search with optional LLM-planned payload filters (ONLY mem_type + mem_category).

        - Keeps existing session filters (user_id/agent_id/run_id/...)
        - LLM decides whether to add mem_type/mem_category filters for faster + more relevant retrieval
        - If results are too few, relax filters in order: mem_category -> mem_type
        """
        # 0) embeddings
        embeddings = self.embedding_model.embed(query, "search")

        # 1) base filters (session scope etc.) - NEVER drop these
        base_filters: Dict[str, Any] = deepcopy(filters or {})

        # 2) LLM planner: decide mem_type/mem_category filters
        plan_filters: Dict[str, Any] = {}
        relax_order: List[str] = ["mem_category", "mem_type"]  # fixed by prompt
        planner_obj: Optional[Dict[str, Any]] = None

        try:
            planner_resp = self.llm.generate_response(
                messages=[
                    {"role": "system", "content": SEARCH_FILTER_PLANNER_PROMPT},
                    {"role": "user", "content": query},
                ],
                response_format={"type": "json_object"},
            )
            planner_resp = remove_code_blocks(planner_resp)

            try:
                planner_obj = json.loads(planner_resp)
            except json.JSONDecodeError:
                planner_obj = json.loads(extract_json(planner_resp))

            if isinstance(planner_obj, dict) and planner_obj.get("use_filters") is True:
                pf = planner_obj.get("filters") or {}
                if isinstance(pf, dict):
                    # strict whitelist: ONLY mem_type/mem_category
                    if pf.get("mem_type") in {"semantic_fact", "episodic_event", "preference", "intention"}:
                        plan_filters["mem_type"] = pf["mem_type"]
                    if pf.get("mem_category") in {
                        "personal_detail", "preference", "plan", "activity", "health",
                        "professional", "relationship", "location", "education", "event", "misc"
                    }:
                        plan_filters["mem_category"] = pf["mem_category"]

                # relax_order 固定即可；若你允许 planner 覆盖，也要白名单
                ro = planner_obj.get("relax_order")
                if isinstance(ro, list):
                    cleaned = [x for x in ro if x in ("mem_category", "mem_type")]
                    if cleaned:
                        relax_order = cleaned

        except Exception as e:
            logger.warning(f"Filter planner failed, fallback to base filters only: {e}")

        # 3) stage A: search with strong filters
        effective_filters = deepcopy(base_filters)
        effective_filters.update(plan_filters)

        memories = self.vector_store.search(
            query=query,
            vectors=embeddings,
            limit=limit,
            filters=effective_filters if effective_filters else None,
        )

        # 4) stage B: relax if too few
        min_hits = max(5, min(20, limit // 3))
        if plan_filters and len(memories) < min_hits:
            relaxed_filters = deepcopy(effective_filters)
            for k in relax_order:
                if len(memories) >= min_hits:
                    break
                # only relax planned keys; never drop base/session keys
                if k in plan_filters:
                    relaxed_filters.pop(k, None)

                    memories = self.vector_store.search(
                        query=query,
                        vectors=embeddings,
                        limit=limit,
                        filters=relaxed_filters if relaxed_filters else None,
                    )

        # 5) formatting (your original logic)
        promoted_payload_keys = [
            "user_id",
            "agent_id",
            "run_id",
            "actor_id",
            "role",
        ]
        core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", *promoted_payload_keys}

        original_memories = []
        for mem in memories:
            memory_item_dict = MemoryItem(
                id=mem.id,
                memory=mem.payload.get("data", ""),
                hash=mem.payload.get("hash"),
                created_at=mem.payload.get("created_at"),
                updated_at=mem.payload.get("updated_at"),
                score=mem.score,
            ).model_dump()

            for key in promoted_payload_keys:
                if key in mem.payload:
                    memory_item_dict[key] = mem.payload[key]

            additional_metadata = {k: v for k, v in mem.payload.items() if k not in core_and_promoted_keys}
            if additional_metadata:
                memory_item_dict["metadata"] = additional_metadata

            if threshold is None or mem.score >= threshold:
                original_memories.append(memory_item_dict)

        return original_memories

    def update(self, memory_id, data):
        """
        Update a memory by ID.

        Args:
            memory_id (str): ID of the memory to update.
            data (str): New content to update the memory with.

        Returns:
            dict: Success message indicating the memory was updated.

        Example:
            >>> m.update(memory_id="mem_123", data="Likes to play tennis on weekends")
            {'message': 'Memory updated successfully!'}
        """
        capture_event("mem0.update", self, {"memory_id": memory_id, "sync_type": "sync"})

        existing_embeddings = {data: self.embedding_model.embed(data, "update")}

        self._update_memory(memory_id, data, existing_embeddings)
        return {"message": "Memory updated successfully!"}

    def delete(self, memory_id):
        """
        Delete a memory by ID.

        Args:
            memory_id (str): ID of the memory to delete.
        """
        capture_event("mem0.delete", self, {"memory_id": memory_id, "sync_type": "sync"})
        self._delete_memory(memory_id)
        return {"message": "Memory deleted successfully!"}

    def delete_all(self, user_id: Optional[str] = None, agent_id: Optional[str] = None, run_id: Optional[str] = None):
        """
        Delete all memories.

        Args:
            user_id (str, optional): ID of the user to delete memories for. Defaults to None.
            agent_id (str, optional): ID of the agent to delete memories for. Defaults to None.
            run_id (str, optional): ID of the run to delete memories for. Defaults to None.
        """
        filters: Dict[str, Any] = {}
        if user_id:
            filters["user_id"] = user_id
        if agent_id:
            filters["agent_id"] = agent_id
        if run_id:
            filters["run_id"] = run_id

        if not filters:
            raise ValueError(
                "At least one filter is required to delete all memories. If you want to delete all memories, use the `reset()` method."
            )

        keys, encoded_ids = process_telemetry_filters(filters)
        capture_event("mem0.delete_all", self, {"keys": keys, "encoded_ids": encoded_ids, "sync_type": "sync"})
        # delete all vector memories and reset the collections
        memories = self.vector_store.list(filters=filters)[0]
        for memory in memories:
            self._delete_memory(memory.id)
        self.vector_store.reset()

        logger.info(f"Deleted {len(memories)} memories")

        if self.enable_graph:
            self.graph.delete_all(filters)

        return {"message": "Memories deleted successfully!"}

    def history(self, memory_id):
        """
        Get the history of changes for a memory by ID.

        Args:
            memory_id (str): ID of the memory to get history for.

        Returns:
            list: List of changes for the memory.
        """
        capture_event("mem0.history", self, {"memory_id": memory_id, "sync_type": "sync"})
        return self.db.get_history(memory_id)

    def _create_memory(self, data, existing_embeddings, metadata=None):
        logger.debug(f"Creating memory with {data=}")
        if data in existing_embeddings:
            embeddings = existing_embeddings[data]
        else:
            embeddings = self.embedding_model.embed(data, memory_action="add")
        memory_id = str(uuid.uuid4())
        metadata = metadata or {}
        metadata["data"] = data
        metadata["hash"] = hashlib.md5(data.encode()).hexdigest()
        metadata["created_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()

        self.vector_store.insert(
            vectors=[embeddings],
            ids=[memory_id],
            payloads=[metadata],
        )
        self.db.add_history(
            memory_id,
            None,
            data,
            "ADD",
            created_at=metadata.get("created_at"),
            actor_id=metadata.get("actor_id"),
            role=metadata.get("role"),
        )
        return memory_id

    def _create_procedural_memory(self, messages, metadata=None, prompt=None):
        """
        Create a procedural memory

        Args:
            messages (list): List of messages to create a procedural memory from.
            metadata (dict): Metadata to create a procedural memory from.
            prompt (str, optional): Prompt to use for the procedural memory creation. Defaults to None.
        """
        logger.info("Creating procedural memory")

        parsed_messages = [
            {"role": "system", "content": prompt or PROCEDURAL_MEMORY_SYSTEM_PROMPT},
            *messages,
            {
                "role": "user",
                "content": "Create procedural memory of the above conversation.",
            },
        ]

        try:
            procedural_memory = self.llm.generate_response(messages=parsed_messages)
            procedural_memory = remove_code_blocks(procedural_memory)
        except Exception as e:
            logger.error(f"Error generating procedural memory summary: {e}")
            raise

        if metadata is None:
            raise ValueError("Metadata cannot be done for procedural memory.")

        metadata["memory_type"] = MemoryType.PROCEDURAL.value
        embeddings = self.embedding_model.embed(procedural_memory, memory_action="add")
        memory_id = self._create_memory(procedural_memory, {procedural_memory: embeddings}, metadata=metadata)
        capture_event("mem0._create_procedural_memory", self, {"memory_id": memory_id, "sync_type": "sync"})

        result = {"results": [{"id": memory_id, "memory": procedural_memory, "event": "ADD"}]}

        return result

    def _update_memory(self, memory_id, data, existing_embeddings, metadata=None):
        logger.info(f"Updating memory with {data=}")

        try:
            existing_memory = self.vector_store.get(vector_id=memory_id)
        except Exception:
            logger.error(f"Error getting memory with ID {memory_id} during update.")
            raise ValueError(f"Error getting memory with ID {memory_id}. Please provide a valid 'memory_id'")

        prev_value = existing_memory.payload.get("data")

        new_metadata = deepcopy(metadata) if metadata is not None else {}

        new_metadata["data"] = data
        new_metadata["hash"] = hashlib.md5(data.encode()).hexdigest()
        new_metadata["created_at"] = existing_memory.payload.get("created_at")
        new_metadata["updated_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()

        # Preserve session identifiers from existing memory only if not provided in new metadata
        if "user_id" not in new_metadata and "user_id" in existing_memory.payload:
            new_metadata["user_id"] = existing_memory.payload["user_id"]
        if "agent_id" not in new_metadata and "agent_id" in existing_memory.payload:
            new_metadata["agent_id"] = existing_memory.payload["agent_id"]
        if "run_id" not in new_metadata and "run_id" in existing_memory.payload:
            new_metadata["run_id"] = existing_memory.payload["run_id"]
        if "actor_id" not in new_metadata and "actor_id" in existing_memory.payload:
            new_metadata["actor_id"] = existing_memory.payload["actor_id"]
        if "role" not in new_metadata and "role" in existing_memory.payload:
            new_metadata["role"] = existing_memory.payload["role"]

        if data in existing_embeddings:
            embeddings = existing_embeddings[data]
        else:
            embeddings = self.embedding_model.embed(data, "update")

        self.vector_store.update(
            vector_id=memory_id,
            vector=embeddings,
            payload=new_metadata,
        )
        logger.info(f"Updating memory with ID {memory_id=} with {data=}")

        self.db.add_history(
            memory_id,
            prev_value,
            data,
            "UPDATE",
            created_at=new_metadata["created_at"],
            updated_at=new_metadata["updated_at"],
            actor_id=new_metadata.get("actor_id"),
            role=new_metadata.get("role"),
        )
        return memory_id

    def _delete_memory(self, memory_id):
        logger.info(f"Deleting memory with {memory_id=}")
        existing_memory = self.vector_store.get(vector_id=memory_id)
        prev_value = existing_memory.payload.get("data", "")
        self.vector_store.delete(vector_id=memory_id)
        self.db.add_history(
            memory_id,
            prev_value,
            None,
            "DELETE",
            actor_id=existing_memory.payload.get("actor_id"),
            role=existing_memory.payload.get("role"),
            is_deleted=1,
        )
        return memory_id

    def reset(self):
        """
        Reset the memory store by:
            Deletes the vector store collection
            Resets the database
            Recreates the vector store with a new client
        """
        logger.warning("Resetting all memories")

        if hasattr(self.db, "connection") and self.db.connection:
            self.db.connection.execute("DROP TABLE IF EXISTS history")
            self.db.connection.close()

        self.db = SQLiteManager(self.config.history_db_path)

        if hasattr(self.vector_store, "reset"):
            self.vector_store = VectorStoreFactory.reset(self.vector_store)
        else:
            logger.warning("Vector store does not support reset. Skipping.")
            self.vector_store.delete_col()
            self.vector_store = VectorStoreFactory.create(
                self.config.vector_store.provider, self.config.vector_store.config
            )
        capture_event("mem0.reset", self, {"sync_type": "sync"})

    def chat(self, query):
        raise NotImplementedError("Chat function not implemented yet.")


class AsyncMemory(MemoryBase):
    def __init__(self, config: MemoryConfig = MemoryConfig()):
        self.config = config

        self.embedding_model = EmbedderFactory.create(
            self.config.embedder.provider,
            self.config.embedder.config,
            self.config.vector_store.config,
        )
        self.vector_store = VectorStoreFactory.create(
            self.config.vector_store.provider, self.config.vector_store.config
        )
        self.llm = LlmFactory.create(self.config.llm.provider, self.config.llm.config)
        self.db = SQLiteManager(self.config.history_db_path)
        self.collection_name = self.config.vector_store.config.collection_name
        self.api_version = self.config.version

        # Initialize reranker if configured
        self.reranker = None
        if config.reranker:
            self.reranker = RerankerFactory.create(
                config.reranker.provider,
                config.reranker.config
            )

        self.enable_graph = False

        if self.config.graph_store.config:
            provider = self.config.graph_store.provider
            self.graph = GraphStoreFactory.create(provider, self.config)
            self.enable_graph = True
        else:
            self.graph = None

        telemetry_config = _safe_deepcopy_config(self.config.vector_store.config)
        telemetry_config.collection_name = "mem0migrations"
        if self.config.vector_store.provider in ["faiss", "qdrant"]:
            provider_path = f"migrations_{self.config.vector_store.provider}"
            telemetry_config.path = os.path.join(mem0_dir, provider_path)
            os.makedirs(telemetry_config.path, exist_ok=True)
        self._telemetry_vector_store = VectorStoreFactory.create(self.config.vector_store.provider, telemetry_config)

        capture_event("mem0.init", self, {"sync_type": "async"})

    @classmethod
    async def from_config(cls, config_dict: Dict[str, Any]):
        try:
            config = cls._process_config(config_dict)
            config = MemoryConfig(**config_dict)
        except ValidationError as e:
            logger.error(f"Configuration validation error: {e}")
            raise
        return cls(config)

    @staticmethod
    def _process_config(config_dict: Dict[str, Any]) -> Dict[str, Any]:
        if "graph_store" in config_dict:
            if "vector_store" not in config_dict and "embedder" in config_dict:
                config_dict["vector_store"] = {}
                config_dict["vector_store"]["config"] = {}
                config_dict["vector_store"]["config"]["embedding_model_dims"] = config_dict["embedder"]["config"][
                    "embedding_dims"
                ]
        try:
            return config_dict
        except ValidationError as e:
            logger.error(f"Configuration validation error: {e}")
            raise

    def _should_use_agent_memory_extraction(self, messages, metadata):
        """Determine whether to use agent memory extraction based on the logic:
        - If agent_id is present and messages contain assistant role -> True
        - Otherwise -> False

        Args:
            messages: List of message dictionaries
            metadata: Metadata containing user_id, agent_id, etc.

        Returns:
            bool: True if should use agent memory extraction, False for user memory extraction
        """
        # Check if agent_id is present in metadata
        has_agent_id = metadata.get("agent_id") is not None

        # Check if there are assistant role messages
        has_assistant_messages = any(msg.get("role") == "assistant" for msg in messages)

        # Use agent memory extraction if agent_id is present and there are assistant messages
        return has_agent_id and has_assistant_messages

    async def add(
            self,
            messages,
            *,
            user_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            run_id: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None,
            infer: bool = True,
            memory_type: Optional[str] = None,
            prompt: Optional[str] = None,
            llm=None,
    ):
        """
        异步创建一条新的记忆。
        参数：
            messages (str 或 List[Dict[str, str]]):
                需要存入记忆的消息内容。
            user_id (str, 可选):
                创建该记忆的用户 ID。
            agent_id (str, 可选):
                创建该记忆的代理（agent）ID，默认为 None。
            run_id (str, 可选):
                创建该记忆的运行（run）ID，默认为 None。
            metadata (dict, 可选):
                与记忆一同存储的元数据，默认为 None。
            infer (bool, 可选):
                是否对记忆进行推断（infer），默认为 True。
            memory_type (str, 可选):
                要创建的记忆类型，默认为 None。
                传入 "procedural_memory" 可创建过程性记忆（程序性记忆）。
            prompt (str, 可选):
                用于记忆创建的提示词（prompt），默认为 None。
            llm (BaseChatModel, 可选):
                用于生成过程性记忆的 LLM 类，默认为 None。
                当用户使用 LangChain 的 ChatModel 时非常有用。
        返回：
            dict:
                包含记忆添加操作结果的字典。
        """

        processed_metadata, effective_filters = _build_filters_and_metadata(
            user_id=user_id, agent_id=agent_id, run_id=run_id, input_metadata=metadata
        )

        if memory_type is not None and memory_type != MemoryType.PROCEDURAL.value:
            raise ValueError(
                f"Invalid 'memory_type'. Please pass {MemoryType.PROCEDURAL.value} to create procedural memories."
            )

        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        elif isinstance(messages, dict):
            messages = [messages]

        elif not isinstance(messages, list):
            raise Mem0ValidationError(
                message="messages must be str, dict, or list[dict]",
                error_code="VALIDATION_003",
                details={"provided_type": type(messages).__name__, "valid_types": ["str", "dict", "list[dict]"]},
                suggestion="Convert your input to a string, dictionary, or list of dictionaries."
            )

        if agent_id is not None and memory_type == MemoryType.PROCEDURAL.value:
            results = await self._create_procedural_memory(
                messages, metadata=processed_metadata, prompt=prompt, llm=llm
            )
            return results

        if self.config.llm.config.get("enable_vision"):
            messages = parse_vision_messages(messages, self.llm, self.config.llm.config.get("vision_details"))
        else:
            messages = parse_vision_messages(messages)

        vector_store_task = asyncio.create_task(
            self._add_to_vector_store(messages, processed_metadata, effective_filters, infer)
        )
        graph_task = asyncio.create_task(self._add_to_graph(messages, effective_filters))

        vector_store_result, graph_result = await asyncio.gather(vector_store_task, graph_task)

        if self.enable_graph:
            return {
                "results": vector_store_result,
                "relations": graph_result,
            }

        return {"results": vector_store_result}

    async def _add_to_vector_store(
            self,
            messages: list,
            metadata: dict,
            effective_filters: dict,
            infer: bool,
    ):
        if not infer:
            # 你已有的 not infer 分支，保持不变
            returned_memories = []
            for message_dict in messages:
                if (
                        not isinstance(message_dict, dict)
                        or message_dict.get("role") is None
                        or message_dict.get("content") is None
                ):
                    logger.warning(f"Skipping invalid message format (async): {message_dict}")
                    continue
                if message_dict["role"] == "system":
                    continue

                per_msg_meta = deepcopy(metadata)
                per_msg_meta["role"] = message_dict["role"]
                actor_name = message_dict.get("name")
                if actor_name:
                    per_msg_meta["actor_id"] = actor_name

                msg_content = message_dict["content"]
                msg_embeddings = await asyncio.to_thread(self.embedding_model.embed, msg_content, "add")
                mem_id = await self._create_memory(msg_content, msg_embeddings, per_msg_meta)

                returned_memories.append(
                    {
                        "id": mem_id,
                        "memory": msg_content,
                        "event": "ADD",
                        "actor_id": actor_name if actor_name else None,
                        "role": message_dict["role"],
                    }
                )
            return returned_memories

        # --------------------------
        # infer=True：对齐异步写入逻辑
        # --------------------------
        parsed_messages = parse_messages(messages)
        user_prompt = f"Input:\n{parsed_messages}"

        def parse_structured_facts(response: str, mem_type: str) -> ExtractionResult:
            fact_texts: List[str] = []
            meta_by_text: Dict[str, Dict[str, Any]] = {}
            try:
                response = remove_code_blocks(response)
                if not response or not response.strip():
                    parsed_obj = {"facts": []}
                else:
                    try:
                        parsed_obj = json.loads(response)
                    except json.JSONDecodeError:
                        extracted_json = extract_json(response)
                        parsed_obj = json.loads(extracted_json)
                facts = parsed_obj.get("facts", [])
                if not isinstance(facts, list):
                    facts = []
                for f in facts:
                    if not isinstance(f, dict):
                        continue
                    text = (f.get("text") or "").strip()
                    if not text:
                        continue
                    fact_texts.append(text)
                    meta = {
                        "fact_schema_version": "structured",
                        "mem_type": mem_type,  # 你也可以不存，取决于库里是否需要
                        "mem_category": f.get("mem_category"),
                    }
                    if MEM_TYPE_ALLOW_TIME.get(mem_type, False):
                        if f.get("time") is not None:
                            meta["time"] = f.get("time")
                    # 清理 None
                    meta = {k: v for k, v in meta.items() if v is not None}
                    meta_by_text[text] = meta
            except Exception:
                return ExtractionResult(mem_type=mem_type, fact_texts=[], meta_by_text={})

            return ExtractionResult(mem_type=mem_type, fact_texts=fact_texts, meta_by_text=meta_by_text)

        async def run_extraction(mem_type: str, system_prompt: str) -> ExtractionResult:
            resp = await asyncio.to_thread(
                self.llm.generate_response,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"},
            )
            return parse_structured_facts(resp, mem_type)

        tasks = [
            run_extraction("profile", USER_PROFILE_MEMORY_EXTRACTION_PROMPT),
            run_extraction("episodic", USER_EPISODIC_MEMORY_EXTRACTION_PROMPT),
            run_extraction("working", USER_WORKING_SESSION_MEMORY_EXTRACTION_PROMPT),
        ]
        profile_res, episodic_res, working_res = await asyncio.gather(*tasks, return_exceptions=False)

        # Search filters（保持 AsyncMemory 原意：用 session ids）
        search_filters = {}
        if effective_filters.get("user_id"):
            search_filters["user_id"] = effective_filters["user_id"]
        if effective_filters.get("agent_id"):
            search_filters["agent_id"] = effective_filters["agent_id"]
        if effective_filters.get("run_id"):
            search_filters["run_id"] = effective_filters["run_id"]

        def _dedup_keep_order(items: List[str]) -> List[str]:
            seen = set()
            out = []
            for x in items:
                x = (x or "").strip()
                if not x or x in seen:
                    continue
                seen.add(x)
                out.append(x)
            return out

        async def build_search_pack_for_extraction(
                self,
                extraction: ExtractionResult,
                search_filters: Dict[str, Any],
                *,
                limit: int = 5,
                embed_op: str = "add",
                logger: Optional[logging.Logger] = None,
        ) -> SearchPack:
            """
            对单个 ExtractionResult 的 fact_texts 做并发 embedding+检索，
            返回该 mem_type 独立的 SearchPack（含临时 id 映射、embedding cache 等）。
            """
            logger = logger or logging.getLogger(__name__)
            fact_texts = _dedup_keep_order(extraction.fact_texts or [])
            async def process_fact_for_search(fact_text: str) -> Tuple[str, Any, List[Dict[str, str]]]:
                embeddings = await asyncio.to_thread(self.embedding_model.embed, fact_text, embed_op)

                # 关键：按 mem_type 过滤，避免 profile/episodic 串层
                typed_filters = dict(search_filters or {})
                typed_filters["mem_type"] = extraction.mem_type

                existing_mems = await asyncio.to_thread(
                    self.vector_store.search,
                    query=fact_text,
                    vectors=embeddings,
                    limit=limit,
                    filters=typed_filters,
                )
                mem_list = [{"id": mem.id, "text": mem.payload.get("data", "")} for mem in existing_mems]
                return fact_text, embeddings, mem_list

            retrieved_old_memory: List[Dict[str, str]] = []
            new_message_embeddings: Dict[str, Any] = {}

            if fact_texts:
                tasks = [process_fact_for_search(t) for t in fact_texts]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for r in results:
                    if isinstance(r, Exception):
                        logger.exception("Error in process_fact_for_search (async)", exc_info=r)
                        continue
                    fact_text, embeddings, mem_list = r
                    new_message_embeddings[fact_text] = embeddings
                    retrieved_old_memory.extend(mem_list)

            # 去重 old memories：按 real uuid 去重 + 保持首次出现顺序（稳定的临时 id）
            seen_ids = set()
            deduped: List[Dict[str, str]] = []
            for item in retrieved_old_memory:
                mid = item.get("id")
                if not mid or mid in seen_ids:
                    continue
                seen_ids.add(mid)
                deduped.append(item)
            retrieved_old_memory = deduped

            logger.info(f"[{extraction.mem_type}] Total existing memories: {len(retrieved_old_memory)}")

            # 映射成临时整数 id，防 UUID hallucination（顺序稳定）
            temp_uuid_mapping: Dict[str, str] = {}
            for idx, item in enumerate(retrieved_old_memory):
                real_id = item["id"]
                tmp_id = str(idx)
                temp_uuid_mapping[tmp_id] = real_id
                item["id"] = tmp_id  # 就地替换成 "0","1","2"... 给 LLM

            return SearchPack(
                mem_type=extraction.mem_type,
                fact_texts=fact_texts,
                new_message_embeddings=new_message_embeddings,
                retrieved_old_memory=retrieved_old_memory,
                temp_uuid_mapping=temp_uuid_mapping,
            )

        async def build_search_packs(
                self,
                extractions: List["ExtractionResult"],
                search_filters: Dict[str, Any],
                *,
                limit: int = 5,
                embed_op: str = "add",
                logger: Optional[logging.Logger] = None,
        ) -> MultiSearchResult:
            """
            对每个 ExtractionResult 单独检索，返回 per_type_searchpack（例如 profile/episodic/working 各一个 SearchPack）。
            不做 merged。
            """
            packs = await asyncio.gather(
                *[
                    build_search_pack_for_extraction(
                        self, ex, search_filters, limit=limit, embed_op=embed_op, logger=logger
                    )
                    for ex in extractions
                ],
                return_exceptions=False,
            )
            per_type_searchpack = {p.mem_type: p for p in packs}
            return MultiSearchResult(per_type_searchpack=per_type_searchpack)

        multi = await build_search_packs(self, [profile_res, episodic_res], search_filters)
        profile_pack = multi.per_type_searchpack["profile"]
        episodic_pack = multi.per_type_searchpack["episodic"]
        # ------------------------------------------------------------
        # LLM 决策：profile / episodic
        # ------------------------------------------------------------
        pack_by_type: Dict[str, SearchPack] = {
            "profile": profile_pack,
            "episodic": episodic_pack,
        }
        extraction_by_type: Dict[str, ExtractionResult] = {
            "profile": profile_res,
            "episodic": episodic_res,
            "working": working_res,
        }

        # 每类可用不同 prompt（没有就用统一）
        update_prompt_by_type = {
            "profile": USER_PROFILE_MEMORY_UPDATE_PROMPT,
            "episodic": USER_EPISODIC_MEMORY_UPDATE_PROMPT,
        }

        ALLOWED_EVENTS = {
            "profile": {"ADD", "UPDATE", "DELETE", "NONE"},
            "episodic": {"ADD", "UPDATE", "DELETE", "NONE"},
        }

        async def decide_actions(mem_type: str) -> Dict[str, Any]:
            pack = pack_by_type[mem_type]
            if not pack.fact_texts:
                return {"memory": []}

            prompt = get_update_memory_messages(
                pack.retrieved_old_memory,
                pack.fact_texts,
                update_prompt_by_type[mem_type],
            )
            try:
                resp = await asyncio.to_thread(
                    self.llm.generate_response,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                logger.exception(f"[{mem_type}] update-memory LLM call failed", exc_info=e)
                return {"memory": []}

            try:
                resp = remove_code_blocks(resp or "")
                obj = json.loads(resp) if resp.strip() else {"memory": []}
                if not isinstance(obj, dict) or not isinstance(obj.get("memory"), list):
                    return {"memory": []}
                return obj
            except Exception as e:
                logger.exception(f"[{mem_type}] invalid JSON from update-memory LLM", exc_info=e)
                return {"memory": []}

        profile_actions, episodic_actions = await asyncio.gather(
            decide_actions("profile"),
            decide_actions("episodic"),
            return_exceptions=False,
        )

        actions_by_type = {
            "profile": profile_actions,
            "episodic": episodic_actions,
        }

        # ------------------------------------------------------------
        # embedding cache：按类型隔离（推荐），也可统一（取决于你希望是否共享）
        # 这里按类型隔离，避免 working 的 action embedding 污染别的类型 cache
        # ------------------------------------------------------------
        embedding_cache_by_type: Dict[str, Dict[str, Any]] = {
            "profile": dict(profile_pack.new_message_embeddings),
            "episodic": dict(episodic_pack.new_message_embeddings),
        }

        async def ensure_embedding(cache: Dict[str, Any], text: str, action: str) -> Any:
            """
            保证 cache[text] 存在。action 用于 embed 的 memory_action（add/update）。
            """
            if text in cache:
                return cache[text]
            emb = await asyncio.to_thread(self.embedding_model.embed, text, action)
            cache[text] = emb
            return emb

        # ------------------------------------------------------------
        # fallback meta：仅用于 profile / episodic
        # ------------------------------------------------------------
        fallback_meta_by_type: Dict[str, Dict[str, Dict[str, Any]]] = {
            "profile": {},
            "episodic": {},
        }

        for mem_type, actions in actions_by_type.items():
            # working 不做 fallback
            if mem_type not in ("profile", "episodic"):
                continue

            meta_by_text = extraction_by_type[mem_type].meta_by_text or {}
            needs_fallback: List[str] = []

            for resp in actions.get("memory", []):
                try:
                    if resp.get("event") not in ("ADD", "UPDATE"):
                        continue
                    t = (resp.get("text") or "").strip()
                    if t and t not in meta_by_text:
                        needs_fallback.append(t)
                except Exception:
                    continue

            if not needs_fallback:
                continue

            try:
                prompt = (
                    FALLBACK_PROFILE_MEMORY_CLASSIFIER_PROMPT
                    if mem_type == "profile"
                    else FALLBACK_EPISODIC_MEMORY_CLASSIFIER_PROMPT
                )

                resp = await asyncio.to_thread(
                    self.llm.generate_response,
                    messages=[
                        {
                            "role": "system",
                            "content": prompt.format(texts=needs_fallback),
                        }
                    ],
                    response_format={"type": "json_object"},
                )

                # -------- parse fallback JSON --------
                resp = remove_code_blocks(resp or "")
                parsed = json.loads(resp) if resp.strip() else {}
                items = parsed.get("items", [])

                if not isinstance(items, list):
                    raise ValueError("Fallback classifier returned invalid format")

                fb_map: Dict[str, Dict[str, Any]] = {}
                for item in items:
                    try:
                        text = (item.get("text") or "").strip()
                        if not text:
                            continue

                        fb_map[text] = {
                            "mem_type": item.get("mem_type"),
                            "mem_category": item.get("mem_category"),
                            "time": item.get("time"),
                            "fact_schema_version": "fallback",
                        }
                    except Exception:
                        continue

                fallback_meta_by_type[mem_type] = fb_map

            except Exception as e:
                logger.exception(f"[{mem_type}] fallback classify failed", exc_info=e)

        # ------------------------------------------------------------
        # 执行动作（每个 mem_type 用自己的 temp_uuid_mapping！！）
        # ------------------------------------------------------------
        write_sem = asyncio.Semaphore(getattr(self.config, "async_write_concurrency", 4))

        async def limited(coro):
            async with write_sem:
                return await coro

        async def update_session_ids(mem_id: str, meta: dict):
            existing_memory = await asyncio.to_thread(self.vector_store.get, vector_id=mem_id)
            updated_metadata = deepcopy(existing_memory.payload)
            if meta.get("agent_id"):
                updated_metadata["agent_id"] = meta["agent_id"]
            if meta.get("run_id"):
                updated_metadata["run_id"] = meta["run_id"]
            updated_metadata["updated_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()

            await asyncio.to_thread(
                self.vector_store.update,
                vector_id=mem_id,
                vector=None,
                payload=updated_metadata,
            )
            logger.info(f"Updated session IDs for memory {mem_id} (async)")

        returned_memories: List[Dict[str, Any]] = []
        user_id = effective_filters.get("user_id") or metadata.get("user_id")

        for mem_type, actions in actions_by_type.items():
            pack = pack_by_type[mem_type]
            temp_uuid_mapping = pack.temp_uuid_mapping
            cache = embedding_cache_by_type[mem_type]

            meta_by_text = extraction_by_type[mem_type].meta_by_text or {}
            fallback_meta = fallback_meta_by_type.get(mem_type, {}) or {}

            memory_tasks: List[Tuple[asyncio.Task, Dict[str, Any], str, Optional[str]]] = []

            for resp in actions.get("memory", []):
                try:
                    event_type = resp.get("event")
                    if event_type not in ALLOWED_EVENTS[mem_type]:
                        continue

                    if event_type in ("ADD", "UPDATE"):
                        action_text = (resp.get("text") or "").strip()
                        if not action_text:
                            continue
                        per_meta = deepcopy(metadata)
                        extra_meta = meta_by_text.get(action_text) or fallback_meta.get(action_text)
                        if extra_meta:
                            per_meta.update(extra_meta)
                        if mem_type == "profile":
                            per_meta["mem_type"] = "profile"
                            if event_type == "ADD":
                                # 1) 向量库写入
                                emb = await ensure_embedding(cache, action_text, "add")
                                task = asyncio.create_task(limited(self._create_memory(action_text, emb, per_meta)))
                                memory_tasks.append((task, resp, "ADD", None))

                                # 2) Redis facts 同步
                                if REDIS_STORE_AVAILABLE and user_id:
                                    try:
                                        await redis_store.add_profile_fact(user_id, action_text)
                                        # 可选：重建字符串快照（推荐，保持 get_profile 兼容）
                                        await redis_store.rebuild_profile_text(user_id, limit=200)
                                    except Exception as e:
                                        logger.warning(f"[profile] Failed to update redis facts/snapshot: {e}")

                            elif event_type == "UPDATE":
                                real_id = temp_uuid_mapping.get(resp.get("id"))
                                if not real_id:
                                    logger.warning(f"[{mem_type}] UPDATE missing id mapping: {resp.get('id')}")
                                    continue

                                emb = await ensure_embedding(cache, action_text, "update")
                                task = asyncio.create_task(
                                    limited(self._update_memory(real_id, action_text, emb, per_meta)))
                                memory_tasks.append((task, resp, "UPDATE", real_id))

                                # Redis facts：用 old_memory -> action_text 做 replace（如果 old_memory 有提供）
                                if REDIS_STORE_AVAILABLE and user_id:
                                    try:
                                        old_text = (resp.get("old_memory") or "").strip()
                                        if old_text:
                                            await redis_store.replace_profile_fact(user_id, old_text, action_text)
                                        else:
                                            # 没有 old_memory 就当 ADD（至少不丢）
                                            await redis_store.add_profile_fact(user_id, action_text)
                                        await redis_store.rebuild_profile_text(user_id, limit=200)
                                    except Exception as e:
                                        logger.warning(f"[profile] Failed to update redis facts/snapshot: {e}")

                        elif mem_type == "episodic":
                            per_meta["mem_type"] = "episodic"
                            if per_meta.get("time"):
                                # 确保 created_at 存在（enrich_mem0_payload_time 需要）
                                if "created_at" not in per_meta:
                                    per_meta["created_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()
                                per_meta = enrich_mem0_payload_time(per_meta)
                            if event_type == "ADD":
                                emb = await ensure_embedding(cache, action_text, "add")
                                task = asyncio.create_task(
                                    limited(self._create_memory(action_text, emb, per_meta))
                                )
                                memory_tasks.append((task, resp, "ADD", None))
                            else:
                                real_id = temp_uuid_mapping.get(resp.get("id"))
                                if not real_id:
                                    logger.warning(f"[{mem_type}] UPDATE missing id mapping: {resp.get('id')}")
                                    continue
                                emb = await ensure_embedding(cache, action_text, "update")
                                task = asyncio.create_task(
                                    limited(self._update_memory(real_id, action_text, emb, per_meta))
                                )
                                memory_tasks.append((task, resp, "UPDATE", real_id))

                    elif event_type == "DELETE":
                        if mem_type == "profile":
                            real_id = temp_uuid_mapping.get(resp.get("id"))
                            if not real_id:
                                logger.warning(f"[{mem_type}] DELETE missing id mapping: {resp.get('id')}")
                                continue
                            # 1) 向量库删除
                            task = asyncio.create_task(limited(self._delete_memory(memory_id=real_id)))
                            memory_tasks.append((task, resp, "DELETE", real_id))

                            # 2) Redis facts 删除（尽量删 text；没有就不动，后续可 rebuild）
                            if REDIS_STORE_AVAILABLE and user_id:
                                try:
                                    t = (resp.get("text") or "").strip()
                                    if t:
                                        await redis_store.remove_profile_fact(user_id, t)
                                    await redis_store.rebuild_profile_text(user_id, limit=200)
                                except Exception as e:
                                    logger.warning(f"[profile] Failed to update redis facts/snapshot: {e}")
                        #to do list
                        elif mem_type == "episodic":
                            real_id = temp_uuid_mapping.get(resp.get("id"))
                            if not real_id:
                                logger.warning(f"[{mem_type}] DELETE missing id mapping: {resp.get('id')}")
                                continue
                            task = asyncio.create_task(limited(self._delete_memory(memory_id=real_id)))
                            memory_tasks.append((task, resp, "DELETE", real_id))

                    elif event_type == "NONE":
                        if mem_type in ("episodic","profile"):
                            real_id = temp_uuid_mapping.get(resp.get("id"))
                            if real_id and (metadata.get("agent_id") or metadata.get("run_id")):
                                task = asyncio.create_task(limited(update_session_ids(real_id, metadata)))
                                memory_tasks.append((task, resp, "NONE", real_id))

                except Exception as e:
                    logger.exception(f"[{mem_type}] Error processing action: {resp}", exc_info=e)
            for task, resp, event_type, mem_id in memory_tasks:
                try:
                    result = await task
                    text = (resp.get("text") or "").strip()
                    if event_type == "ADD":
                        returned_memories.append(
                            {"id": result, "memory": text, "event": "ADD", "mem_type": mem_type})
                        if mem_type == "episodic" and REDIS_STORE_AVAILABLE and user_id and text:
                            try:
                                await redis_store.add_episodic_to_cache(user_id, text)
                            except Exception as e:
                                logger.warning(f"[episodic] Failed to cache newly added memory: {e}")
                    elif event_type == "UPDATE":
                        returned_memories.append({
                            "id": mem_id,
                            "memory": resp.get("text"),
                            "event": "UPDATE",
                            "previous_memory": resp.get("old_memory"),
                            "mem_type": mem_type,
                        })
                        if mem_type == "episodic" and REDIS_STORE_AVAILABLE and user_id and text:
                            try:
                                await redis_store.add_episodic_to_cache(user_id, text)
                            except Exception as e:
                                logger.warning(f"[episodic] Failed to cache updated memory: {e}")
                    elif event_type == "DELETE":
                        returned_memories.append(
                            {"id": mem_id, "memory": resp.get("text"), "event": "DELETE", "mem_type": mem_type})
                except Exception as e:
                    logger.exception(f"[{mem_type}] Error awaiting write task", exc_info=e)

        if REDIS_STORE_AVAILABLE and user_id and working_res.fact_texts:
            try:
                for fact_text in working_res.fact_texts:
                    if fact_text and fact_text.strip():
                        await redis_store.add_working_memory(user_id, {
                            "text": fact_text,
                            "type": "working",
                            "mem_category": working_res.meta_by_text.get(fact_text, {}).get("mem_category"),
                            "emotion": working_res.meta_by_text.get(fact_text, {}).get("emotion"),
                        })
                        returned_memories.append({
                            "id": "redis_working",
                            "memory": fact_text,
                            "event": "ADD",
                            "mem_type": "working"
                        })
            except Exception as e:
                logger.exception(f"[working] Error saving working memories to redis", exc_info=e)

        # telemetry & return
        keys, encoded_ids = process_telemetry_filters(effective_filters)
        capture_event(
            "mem0.add",
            self,
            {"version": self.api_version, "keys": keys, "encoded_ids": encoded_ids, "sync_type": "async"},
        )
        return returned_memories

    async def _add_to_graph(self, messages, filters):
        added_entities = []
        if self.enable_graph:
            if filters.get("user_id") is None:
                filters["user_id"] = "user"

            data = "\n".join([msg["content"] for msg in messages if "content" in msg and msg["role"] != "system"])
            added_entities = await asyncio.to_thread(self.graph.add, data, filters)

        return added_entities

    async def get(self, memory_id):
        """
        Retrieve a memory by ID asynchronously.

        Args:
            memory_id (str): ID of the memory to retrieve.

        Returns:
            dict: Retrieved memory.
        """
        capture_event("mem0.get", self, {"memory_id": memory_id, "sync_type": "async"})
        memory = await asyncio.to_thread(self.vector_store.get, vector_id=memory_id)
        if not memory:
            return None

        promoted_payload_keys = [
            "user_id",
            "agent_id",
            "run_id",
            "actor_id",
            "role",
        ]

        core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", *promoted_payload_keys}

        result_item = MemoryItem(
            id=memory.id,
            memory=memory.payload.get("data", ""),
            hash=memory.payload.get("hash"),
            created_at=memory.payload.get("created_at"),
            updated_at=memory.payload.get("updated_at"),
        ).model_dump()

        for key in promoted_payload_keys:
            if key in memory.payload:
                result_item[key] = memory.payload[key]

        additional_metadata = {k: v for k, v in memory.payload.items() if k not in core_and_promoted_keys}
        if additional_metadata:
            result_item["metadata"] = additional_metadata

        return result_item

    async def get_all(
            self,
            *,
            user_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            run_id: Optional[str] = None,
            filters: Optional[Dict[str, Any]] = None,
            limit: int = 100,
    ):
        """
        List all memories.

         Args:
             user_id (str, optional): user id
             agent_id (str, optional): agent id
             run_id (str, optional): run id
             filters (dict, optional): Additional custom key-value filters to apply to the search.
                 These are merged with the ID-based scoping filters. For example,
                 `filters={"actor_id": "some_user"}`.
             limit (int, optional): The maximum number of memories to return. Defaults to 100.

         Returns:
             dict: A dictionary containing a list of memories under the "results" key,
                   and potentially "relations" if graph store is enabled. For API v1.0,
                   it might return a direct list (see deprecation warning).
                   Example for v1.1+: `{"results": [{"id": "...", "memory": "...", ...}]}`
        """

        _, effective_filters = _build_filters_and_metadata(
            user_id=user_id, agent_id=agent_id, run_id=run_id, input_filters=filters
        )

        if not any(key in effective_filters for key in ("user_id", "agent_id", "run_id")):
            raise ValueError(
                "When 'conversation_id' is not provided (classic mode), "
                "at least one of 'user_id', 'agent_id', or 'run_id' must be specified for get_all."
            )

        keys, encoded_ids = process_telemetry_filters(effective_filters)
        capture_event(
            "mem0.get_all", self, {"limit": limit, "keys": keys, "encoded_ids": encoded_ids, "sync_type": "async"}
        )

        vector_store_task = asyncio.create_task(self._get_all_from_vector_store(effective_filters, limit))

        graph_task = None
        if self.enable_graph:
            graph_get_all = getattr(self.graph, "get_all", None)
            if callable(graph_get_all):
                if asyncio.iscoroutinefunction(graph_get_all):
                    graph_task = asyncio.create_task(graph_get_all(effective_filters, limit))
                else:
                    graph_task = asyncio.create_task(asyncio.to_thread(graph_get_all, effective_filters, limit))

        results_dict = {}
        if graph_task:
            vector_store_result, graph_entities_result = await asyncio.gather(vector_store_task, graph_task)
            results_dict.update({"results": vector_store_result, "relations": graph_entities_result})
        else:
            results_dict.update({"results": await vector_store_task})

        return results_dict

    async def _get_all_from_vector_store(self, filters, limit):
        memories_result = await asyncio.to_thread(self.vector_store.list, filters=filters, limit=limit)

        # Handle different vector store return formats by inspecting first element
        if isinstance(memories_result, (tuple, list)) and len(memories_result) > 0:
            first_element = memories_result[0]

            # If first element is a container, unwrap one level
            if isinstance(first_element, (list, tuple)):
                actual_memories = first_element
            else:
                # First element is a memory object, structure is already flat
                actual_memories = memories_result
        else:
            actual_memories = memories_result

        promoted_payload_keys = [
            "user_id",
            "agent_id",
            "run_id",
            "actor_id",
            "role",
        ]
        core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", *promoted_payload_keys}

        formatted_memories = []
        for mem in actual_memories:
            memory_item_dict = MemoryItem(
                id=mem.id,
                memory=mem.payload.get("data", ""),
                hash=mem.payload.get("hash"),
                created_at=mem.payload.get("created_at"),
                updated_at=mem.payload.get("updated_at"),
            ).model_dump(exclude={"score"})

            for key in promoted_payload_keys:
                if key in mem.payload:
                    memory_item_dict[key] = mem.payload[key]

            additional_metadata = {k: v for k, v in mem.payload.items() if k not in core_and_promoted_keys}
            if additional_metadata:
                memory_item_dict["metadata"] = additional_metadata

            formatted_memories.append(memory_item_dict)

        return formatted_memories

    from typing import Any, Dict,  Optional, TypedDict

    class LayeredSearchResult(TypedDict):
        profile: List[Dict[str, Any]]
        episodic: List[Dict[str, Any]]
        working: List[Dict[str, Any]]

    def _filter_and_rank_by_time(
            self,
            memories: list,
            query: str,
            reference_time: datetime,
            *,
            limit: int | None = None,
            min_keep_if_time_query: int = 3,
            time_query_candidate_mul: int = 5,
            use_recency_when_no_time: bool = True,
            recency_tau_days: float = 60.0,
            recency_alpha: float = 0.15,
    ) -> list:
        """
        Upgraded episodic time-aware filtering & ranking.

        Key behaviors:
        - If query contains a time expression:
            1) Extract best time expression (longest/highest-priority).
            2) Hard-filter by overlap on [ts_start_epoch, ts_end_epoch] (prefer time_is_event==1).
            3) Time-aware re-score using Jaccard overlap + center-distance decay.
            4) If results < limit/min_keep_if_time_query, softly backfill from:
                a) time_is_event==0 (unknown event time) with penalty
                b) non-overlap but semantically strong items (with heavy penalty)
        - If no time expression:
            - Optionally apply a mild recency bias using dialogue_ts_epoch (or created_at fallback).

        Assumptions:
        - Each mem item has attributes: .payload (dict) and optionally .score (float).
        - payload fields (episodic):
            ts_start_epoch, ts_end_epoch, time_is_event (0/1), dialogue_ts_epoch (int seconds),
            created_at (ISO), dialogue_ts (ISO) etc.

        Returns:
            A new list of mem objects (original objects untouched; ranking uses computed scores).
        """
        import re
        import math
        from datetime import datetime as _dt

        # Local imports (your module)
        from mem0.memory.time_metadata_builder import _parse_time_range_cn, _parse_iso_dt, _epoch_seconds

        logger = globals().get("logger", None)

        def _log_info(msg: str):
            if logger:
                logger.info(msg)

        def _log_debug(msg: str):
            if logger:
                logger.debug(msg)

        def _safe_score(m) -> float:
            try:
                s = getattr(m, "score", None)
                return float(s) if s is not None else 0.0
            except Exception:
                return 0.0

        def _get_payload(m) -> dict:
            try:
                return m.payload if hasattr(m, "payload") and isinstance(m.payload, dict) else {}
            except Exception:
                return {}

        def _extract_best_time_text(q: str) -> str | None:
            """
            Find all candidate time expressions and pick the best one:
            - Prefer higher-priority patterns
            - For same priority, prefer longer match (more specific)
            """
            q0 = (q or "").strip()
            if not q0:
                return None

            # Priority: more specific / longer patterns first
            # NOTE: patterns cover CN digits and "半"
            patterns = [
                # explicit year-month / year-month-day
                r"((19|20)\d{2})年(\d{1,2})月(\d{1,2})[日号]?",
                r"((19|20)\d{2})年[0-9一二两三四五六七八九十]+月",
                # relative year + month
                r"(去年|今年|明年)[0-9一二两三四五六七八九十]+月",
                # week+weekday with modifier
                r"(上上周|上上星期|上周|上星期|本周|这周|这星期|本星期|下周|下星期)(周|星期)[一二三四五六日天]",
                # week/month keywords
                r"(上上周|上上星期|上周|上星期|本周|这周|这星期|本星期|下周|下星期)",
                r"(上月|上个月|本月|这个月|这月|下月|下个月)",
                # relative day keywords
                r"(今天|昨日|昨天|昨晚|前天|明天|明晚|后天)",
                # X days/weeks/months/years before/after (CN digits + 半 + arabic)
                r"([0-9一二两三四五六七八九十半]+)天(前|后)",
                r"([0-9一二两三四五六七八九十半]+)周(前|后)",
                r"([0-9一二两三四五六七八九十半]+)个?月(前|后)",
                r"([0-9一二两三四五六七八九十半]+)年(前|后)",
                # weekday (recent)
                r"(周|星期)[一二三四五六日天]",
                # month/day without year
                r"(\d{1,2})月(\d{1,2})[日号]?",
                # month-only (CN digits / arabic)
                r"[0-9一二两三四五六七八九十]+月",
                # year only
                r"((19|20)\d{2})年",
                # year keywords
                r"(去年|今年|明年)",
            ]

            best = None
            best_pri = 10 ** 9
            best_len = -1

            for pri, pat in enumerate(patterns):
                try:
                    for m in re.finditer(pat, q0):
                        txt = m.group(0)
                        if not txt:
                            continue
                        L = len(txt)
                        if pri < best_pri or (pri == best_pri and L > best_len):
                            best = txt
                            best_pri = pri
                            best_len = L
                except re.error:
                    continue

            return best

        def _payload_epoch_from_iso(iso_str: str) -> int | None:
            try:
                dt = _parse_iso_dt(iso_str)
                return _epoch_seconds(dt)
            except Exception:
                return None

        def _get_dialogue_epoch(payload: dict) -> int | None:
            # Prefer dialogue_ts_epoch if present; else fallback to created_at / dialogue_ts ISO.
            v = payload.get("dialogue_ts_epoch")
            if isinstance(v, (int, float)):
                return int(v)
            for k in ("dialogue_ts", "created_at"):
                if payload.get(k):
                    ep = _payload_epoch_from_iso(payload[k])
                    if ep is not None:
                        return ep
            return None

        def _compute_time_score(
                original: float,
                *,
                q_start: int,
                q_end: int,
                m_start: int,
                m_end: int,
                time_is_event: int,
        ) -> float:
            """
            Time-aware score multiplier:
            - Jaccard overlap between intervals (preferred)
            - Center-distance decay
            - time_is_event penalty (unknown time shouldn't dominate)
            """
            # Ensure valid intervals
            if m_end < m_start:
                m_start, m_end = m_end, m_start
            if q_end < q_start:
                q_start, q_end = q_end, q_start

            q_span = max(q_end - q_start, 1)
            m_span = max(m_end - m_start, 1)

            # Overlap
            overlap_start = max(m_start, q_start)
            overlap_end = min(m_end, q_end)
            overlap = max(0, overlap_end - overlap_start)

            union = m_span + q_span - overlap
            jaccard = (overlap / union) if union > 0 else 0.0  # [0,1]

            # Centers
            q_center = (q_start + q_end) / 2.0
            m_center = (m_start + m_end) / 2.0
            center_dist = abs(m_center - q_center)

            denom = max(q_span, 86400)  # at least 1 day scale for stability
            distance_w = 1.0 / (1.0 + center_dist / (denom * 2.0))  # (0,1]

            event_boost = 1.0 if int(time_is_event or 0) == 1 else 0.6
            time_weight = event_boost * (0.7 * jaccard + 0.3 * distance_w)  # [0, ~1]

            # Multiply original score
            return original * (1.0 + time_weight)

        def _apply_recency_boost(original: float, age_days: float) -> float:
            """
            Mild recency bias:
            adjusted = score * (1 + alpha * exp(-age/tau))
            """
            try:
                boost = math.exp(-max(age_days, 0.0) / max(recency_tau_days, 1e-6))
            except Exception:
                boost = 0.0
            return original * (1.0 + float(recency_alpha) * boost)

        # ---------------------------
        # 0) Prepare
        # ---------------------------
        if not memories:
            return memories

        # If caller doesn't pass limit, infer from input size (no truncation)
        effective_limit = int(limit) if isinstance(limit, int) and limit > 0 else None

        # Optional: caller may pass more candidates already. If time query, we can keep more internally.
        # (Do NOT slice here unless you want to cap compute; caller can pre-slice to limit*k)
        # ---------------------------
        # 1) Extract time expression
        # ---------------------------
        time_text = _extract_best_time_text(query)
        query_time_range = None  # (epoch_start, epoch_end)

        if time_text:
            try:
                iso_start, iso_end = _parse_time_range_cn(time_text, reference_time)
                q_start = _epoch_seconds(_parse_iso_dt(iso_start))
                q_end = _epoch_seconds(_parse_iso_dt(iso_end))
                query_time_range = (q_start, q_end)
                _log_info(f"[episodic] time_text='{time_text}' -> range=({q_start},{q_end})")
            except Exception as e:
                _log_debug(f"[episodic] failed parse time_text='{time_text}': {e}")
                query_time_range = None

        # ---------------------------
        # 2) No time intent -> optional recency bias only
        # ---------------------------
        if not query_time_range:
            if not use_recency_when_no_time:
                return memories

            now_epoch = int(reference_time.timestamp())
            scored = []
            for m in memories:
                payload = _get_payload(m)
                base = _safe_score(m)
                d_ep = _get_dialogue_epoch(payload)
                if d_ep is None:
                    scored.append((base, m))
                    continue
                age_days = (now_epoch - d_ep) / 86400.0
                adj = _apply_recency_boost(base, age_days)
                scored.append((adj, m))

            scored.sort(key=lambda x: x[0], reverse=True)
            out = [m for _, m in scored]
            if effective_limit is not None:
                out = out[:effective_limit]
            return out

        # ---------------------------
        # 3) Time intent -> hard filter by overlap, then time-aware re-score
        # ---------------------------
        q_start, q_end = query_time_range

        overlap_event: list[tuple[float, Any]] = []
        overlap_unknown: list[tuple[float, Any]] = []
        no_time_info: list[tuple[float, Any]] = []
        non_overlap: list[tuple[float, Any]] = []

        for m in memories:
            payload = _get_payload(m)
            base = _safe_score(m)

            ts_s = payload.get("ts_start_epoch")
            ts_e = payload.get("ts_end_epoch")
            time_is_event = int(payload.get("time_is_event", 0) or 0)

            # No time metadata at all
            if ts_s is None or ts_e is None:
                # Keep for possible backfill, but penalize (unknown time)
                no_time_info.append((base * 0.5, m))
                continue

            try:
                ts_s = int(ts_s)
                ts_e = int(ts_e)
            except Exception:
                no_time_info.append((base * 0.5, m))
                continue

            has_overlap = not (ts_e < q_start or ts_s > q_end)

            if not has_overlap:
                # Keep as last-resort backfill (heavy penalty)
                non_overlap.append((base * 0.2, m))
                continue

            # Overlap => time-aware score
            adj = _compute_time_score(base, q_start=q_start, q_end=q_end, m_start=ts_s, m_end=ts_e,
                                      time_is_event=time_is_event)

            if time_is_event == 1:
                overlap_event.append((adj, m))
            else:
                # time_is_event==0: overlap exists only because we used created_at as point; keep but lower
                overlap_unknown.append((adj * 0.8, m))

        # Sort each bucket
        overlap_event.sort(key=lambda x: x[0], reverse=True)
        overlap_unknown.sort(key=lambda x: x[0], reverse=True)
        no_time_info.sort(key=lambda x: x[0], reverse=True)
        non_overlap.sort(key=lambda x: x[0], reverse=True)

        # Compose final list with priority
        merged_scored: list[tuple[float, Any]] = []
        merged_scored.extend(overlap_event)
        merged_scored.extend(overlap_unknown)

        # Determine how many we want
        want = effective_limit if effective_limit is not None else None

        # If overlap results too few, backfill cautiously
        def _count_now() -> int:
            return len(merged_scored)

        # Ensure at least min_keep_if_time_query if possible
        target_min = min_keep_if_time_query if (want is None) else min(min_keep_if_time_query, want)

        if _count_now() < target_min:
            # Prefer unknown-time overlap first, already included; now backfill no_time_info then non_overlap
            merged_scored.extend(no_time_info)
            merged_scored.extend(non_overlap)

        # If want is specified, trim
        if want is not None:
            merged_scored = merged_scored[:want]

        out = [m for _, m in merged_scored]

        _log_info(
            f"[episodic] time_filter: input={len(memories)} "
            f"overlap_event={len(overlap_event)} overlap_unknown={len(overlap_unknown)} "
            f"no_time={len(no_time_info)} non_overlap={len(non_overlap)} -> output={len(out)}"
        )

        return out

    async def _search_vector_store(
            self,
            query: str,
            filters: Optional[Dict[str, Any]],
            limit: int,
            threshold: Optional[float] = None,
            rerank: bool = True,
    ) -> LayeredSearchResult:
        """
        Final optimized version (no episodic 5→3).

        Key latency wins:
        - Start embeddings in background BUT do not await until we *know* vector search is needed.
        - Redis 3-layer reads in parallel.
        - LLM decision + LLM redis-filter in parallel.
        - Vector store searches per-layer in parallel.
        - Rerank per-layer in parallel.
        - Merge is sync (cheap).

        Notes:
        - working layer never queries vector store (Redis only).
        - episodic time filter is applied to vector results (kept as before).
        """
        from datetime import datetime
        user_id = (filters or {}).get("user_id")
        reference_time = datetime.now(pytz.timezone("US/Pacific"))

        # -------------------------
        # Optional: global concurrency limiter for heavy blocking ops
        # (embed / vector_store / reranker / llm)
        # -------------------------
        # You can tune this number based on your infra / CPU cores / rate limits.
        sem: asyncio.Semaphore = getattr(self, "_search_sem", None)  # type: ignore
        if sem is None:
            sem = asyncio.Semaphore(8)
            setattr(self, "_search_sem", sem)

        async def _to_thread_limited(fn, *args, **kwargs):
            async with sem:
                return await asyncio.to_thread(fn, *args, **kwargs)

        # -------------------------
        # 0) Fire embeddings early, but DON'T await yet
        # -------------------------
        embed_task: asyncio.Task | None = None
        if query and query.strip():
            embed_task = asyncio.create_task(
                _to_thread_limited(self.embedding_model.embed, query, "search")
            )

        # -------------------------
        # 1) Redis 3-layer reads (parallel)
        # -------------------------
        async def _redis_profile() -> List[Dict[str, Any]]:
            if not REDIS_STORE_AVAILABLE or not user_id:
                return []
            try:
                profile_text = await redis_store.get_profile(user_id)
                if profile_text:
                    return [{
                        "id": "redis_profile",
                        "memory": profile_text,
                        "mem_type": "profile",
                        "source": "redis",
                    }]
            except Exception as e:
                logger.warning(f"[profile] Error reading redis: {e}")
            return []

        async def _redis_episodic(topk: int) -> List[Dict[str, Any]]:
            if not REDIS_STORE_AVAILABLE or not user_id:
                return []
            try:
                cached = await redis_store.get_episodic_cache_recent(user_id, limit=topk*4)
                # keep your prior behavior
                recent = list(reversed(cached))
                out: List[Dict[str, Any]] = []
                for i, mem in enumerate(recent):
                    text = mem if isinstance(mem, str) else (mem.get("text", "") if isinstance(mem, dict) else str(mem))
                    if text:
                        out.append({
                            "id": f"redis_episodic_{i}",
                            "memory": text,
                            "mem_type": "episodic",
                            "source": "redis",
                        })
                return out
            except Exception as e:
                logger.warning(f"[episodic] Error reading redis: {e}")
            return []

        async def _redis_working(topk: int) -> List[Dict[str, Any]]:
            if not REDIS_STORE_AVAILABLE or not user_id:
                return []
            try:
                working = await redis_store.get_working_memories(user_id, limit=topk*4)
                working = list(reversed(working))
                out: List[Dict[str, Any]] = []
                for i, mem in enumerate(working):
                    text = mem.get("text", "") if isinstance(mem, dict) else str(mem)
                    if text:
                        out.append({
                            "id": f"redis_working_{i}",
                            "memory": text,
                            "mem_type": "working",
                            "metadata": mem if isinstance(mem, dict) else {},
                            "source": "redis",
                        })
                return out
            except Exception as e:
                logger.warning(f"[working] Error reading redis: {e}")
            return []

        profile_redis, episodic_redis, working_redis = await asyncio.gather(
            _redis_profile(),
            _redis_episodic(limit),
            _redis_working(limit),
        )

        three_layer_results: Dict[str, List[Dict[str, Any]]] = {
            "profile": profile_redis,
            "episodic": episodic_redis,
            "working": working_redis,
        }

        def _flatten(layered: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for name in ("profile", "episodic", "working"):
                out.extend(layered.get(name, []))
            return out

        all_redis_results = _flatten(three_layer_results)
        need_vector_search = False
        target_layers: List[str] = []

        # -------------------------
        # 2) LLM decision + LLM redis-filter (parallel)
        # -------------------------
        async def _filter_redis_layers(query_text: str, layered: Dict[str, List[Dict[str, Any]]]) -> Dict[
            str, List[Dict[str, Any]]]:
            user_payload = {
                "query": query_text,
                "profile": layered.get("profile", []),
                "episodic": layered.get("episodic", []),
                "working": layered.get("working", []),
            }

            resp = await _to_thread_limited(
                self.llm.generate_response,
                messages=[
                    {"role": "system", "content": REDIS_LAYER_FILTER_PROMPT},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                response_format={"type": "json_object"},
            )
            resp = remove_code_blocks(resp)
            obj = json.loads(resp) if resp.strip() else {}

            def _safe_list(x: Any) -> List[Dict[str, Any]]:
                return x if isinstance(x, list) else []

            return {
                "profile": _safe_list(obj.get("profile")),
                "episodic": _safe_list(obj.get("episodic")),
                "working": _safe_list(obj.get("working")),
            }

        if REDIS_STORE_AVAILABLE and user_id:
            try:
                profile_memories = "\n".join(
                    [f"  - {r.get('memory', '')[:200]}..." for r in three_layer_results["profile"][:1]]
                ) if three_layer_results["profile"] else "  None"

                episodic_memories = "\n".join(
                    [f"  - {r.get('memory', '')[:200]}..." for r in three_layer_results["episodic"][:5]]
                ) if three_layer_results["episodic"] else "  None"

                working_memories = "\n".join(
                    [f"  - {r.get('memory', '')[:200]}..." for r in three_layer_results["working"][:5]]
                ) if three_layer_results["working"] else "  None"

                decision_prompt = f"""Query: {query}

    Redis Memories (recent items, no similarity scores):

    - Profile Memory:
    {profile_memories}

    - Episodic Memory:
    {episodic_memories}

    - Working Memory:
    {working_memories}

    Total Redis Results: {len(all_redis_results)}
    """
                current_date = datetime.now().strftime("%Y-%m-%d")

                decision_task = _to_thread_limited(
                    self.llm.generate_response,
                    messages=[
                        {"role": "system", "content": VECTOR_SEARCH_DECISION_PROMPT.format(current_date=current_date)},
                        {"role": "user", "content": decision_prompt},
                    ],
                    response_format={"type": "json_object"},
                )
                filter_task = _filter_redis_layers(query, three_layer_results)

                decision_response, filtered_three_layer_results = await asyncio.gather(decision_task, filter_task)

                three_layer_results = filtered_three_layer_results
                all_redis_results = _flatten(three_layer_results)

                decision_response = remove_code_blocks(decision_response)
                decision_obj = json.loads(decision_response) if decision_response.strip() else {}

                need_vector_search = bool(decision_obj.get("need_vector_search", False))
                target_layers = decision_obj.get("target_layers") or []
                target_layers = [l for l in target_layers if isinstance(l, str)]
                target_layers = [l for l in target_layers if l in ("profile", "episodic")]  # working never vector

                # de-dup keep order
                seen = set()
                target_layers = [l for l in target_layers if not (l in seen or seen.add(l))]

                if need_vector_search and not target_layers:
                    target_layers = ["profile", "episodic"]

                if (not need_vector_search) and (len(all_redis_results) < 2):
                    need_vector_search = True
                    if not target_layers:
                        target_layers = ["profile", "episodic"]

                if need_vector_search:
                    logger.info(
                        f"LLM decided to search vector store on layers={target_layers}: {decision_obj.get('reason')}")
                else:
                    logger.info(f"LLM decided Redis results are sufficient: {decision_obj.get('reason')}")

            except Exception as e:
                logger.exception("Error in LLM decision/filter", exc_info=e)
                all_redis_results = _flatten(three_layer_results)
                need_vector_search = len(all_redis_results) < 3
                if need_vector_search and not target_layers:
                    target_layers = ["profile", "episodic"]

        # -------------------------
        # 3) If no vector search, cancel embeddings and return redis (filtered)
        # -------------------------
        if not need_vector_search:
            if embed_task is not None and not embed_task.done():
                embed_task.cancel()
            return {
                "profile": three_layer_results["profile"],
                "episodic": three_layer_results["episodic"],
                "working": three_layer_results["working"],
            }

        # -------------------------
        # 4) Need vector search -> await embeddings (only now)
        # -------------------------
        if embed_task is None:
            embeddings = await _to_thread_limited(self.embedding_model.embed, query, "search")
        else:
            embeddings = await embed_task

        base_filters: Dict[str, Any] = deepcopy(filters or {})

        promoted_payload_keys = ["user_id", "agent_id", "run_id", "actor_id", "role"]
        core_and_promoted_keys = {"data", "hash", "created_at", "updated_at", "id", *promoted_payload_keys}

        vector_layer_results: Dict[str, List[Dict[str, Any]]] = {"profile": [], "episodic": [], "working": []}

        async def _search_single_layer(layer: str) -> Tuple[str, List[Dict[str, Any]]]:
            if layer not in ("profile", "episodic"):
                return layer, []

            effective_filters = deepcopy(base_filters)
            effective_filters["mem_type"] = layer

            # Vector search (blocking)
            layer_vector_memories = await _to_thread_limited(
                self.vector_store.search,
                query=query,
                vectors=embeddings,
                limit=limit*2,
                filters=effective_filters if effective_filters else None,
            )

            # Time filter for episodic (keep your behavior; pass limit if you want to cap)
            if layer == "episodic":
                # NOTE: this may apply recency bias even if query has no explicit time,
                # depending on use_recency_when_no_time default.
                layer_vector_memories = self._filter_and_rank_by_time(
                    memories=layer_vector_memories,
                    query=query,
                    reference_time=reference_time,
                    limit=limit,
                )

            formatted: List[Dict[str, Any]] = []
            cache_tasks: List[asyncio.Task] = []

            for mem in layer_vector_memories:
                memory_item_dict = MemoryItem(
                    id=mem.id,
                    memory=mem.payload.get("data", ""),
                    hash=mem.payload.get("hash"),
                    created_at=mem.payload.get("created_at"),
                    updated_at=mem.payload.get("updated_at"),
                    score=mem.score,
                ).model_dump()

                # promoted keys
                for key in promoted_payload_keys:
                    if key in mem.payload:
                        memory_item_dict[key] = mem.payload[key]

                additional_metadata = {k: v for k, v in mem.payload.items() if k not in core_and_promoted_keys}
                if additional_metadata:
                    memory_item_dict["metadata"] = additional_metadata

                if threshold is None or (mem.score is not None and mem.score >= threshold):
                    memory_item_dict.setdefault("mem_type", layer)
                    memory_item_dict["source"] = "vector"
                    formatted.append(memory_item_dict)

                    # async cache episodic
                    if layer == "episodic" and REDIS_STORE_AVAILABLE and user_id:
                        cache_tasks.append(asyncio.create_task(
                            redis_store.add_episodic_to_cache(user_id, memory_item_dict.get("memory", ""))
                        ))

            if cache_tasks:
                # don't fail the whole request if cache fails
                await asyncio.gather(*cache_tasks, return_exceptions=True)

            return layer, formatted

        # -------------------------
        # 5) Vector searches per-layer in parallel
        # -------------------------
        search_tasks = [asyncio.create_task(_search_single_layer(layer)) for layer in target_layers]
        layer_results = await asyncio.gather(*search_tasks)

        for layer, items in layer_results:
            if layer in vector_layer_results:
                vector_layer_results[layer] = items

        # -------------------------
        # 6) Rerank per-layer in parallel (vector items only)
        # -------------------------
        if rerank and self.reranker:
            async def _rerank_single_layer(layer: str) -> Tuple[str, List[Dict[str, Any]]]:
                items = vector_layer_results.get(layer) or []
                if not items:
                    return layer, items
                try:
                    feed_k = min(len(items), max(limit * 3, limit))
                    reranked = await _to_thread_limited(self.reranker.rerank, query, items[:feed_k], limit)
                    return layer, reranked[:limit]
                except Exception as e:
                    logger.warning(f"[{layer}] rerank failed, keep original vector order: {e}")
                    return layer, items

            rr_tasks = []
            for layer in ("profile", "episodic"):
                if vector_layer_results.get(layer):
                    rr_tasks.append(asyncio.create_task(_rerank_single_layer(layer)))

            if rr_tasks:
                rr_results = await asyncio.gather(*rr_tasks)
                for layer, items in rr_results:
                    vector_layer_results[layer] = items

        # -------------------------
        # 7) Merge vector + redis (sync; cheap)
        # -------------------------
        def _merge_layer(redis_list: List[Dict[str, Any]], vector_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            merged: List[Dict[str, Any]] = []
            seen_texts = set()
            # vector first, then redis
            for item in (*vector_list, *redis_list):
                text = item.get("memory", "")
                if not text or text in seen_texts:
                    continue
                seen_texts.add(text)
                merged.append(item)
            return merged

        return {
            "profile": _merge_layer(three_layer_results.get("profile", []), vector_layer_results.get("profile", [])),
            "episodic": _merge_layer(three_layer_results.get("episodic", []), vector_layer_results.get("episodic", [])),
            "working": _merge_layer(three_layer_results.get("working", []), vector_layer_results.get("working", [])),
        }

    def _process_metadata_filters(self, metadata_filters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process enhanced metadata filters and convert them to vector store compatible format.

        Args:
            metadata_filters: Enhanced metadata filters with operators

        Returns:
            Dict of processed filters compatible with vector store
        """
        processed_filters = {}

        def process_condition(key: str, condition: Any) -> Dict[str, Any]:
            if not isinstance(condition, dict):
                # Simple equality: {"key": "value"}
                if condition == "*":
                    # Wildcard: match everything for this field (implementation depends on vector store)
                    return {key: "*"}
                return {key: condition}

            result = {}
            for operator, value in condition.items():
                # Map platform operators to universal format that can be translated by each vector store
                operator_map = {
                    "eq": "eq", "ne": "ne", "gt": "gt", "gte": "gte",
                    "lt": "lt", "lte": "lte", "in": "in", "nin": "nin",
                    "contains": "contains", "icontains": "icontains"
                }

                if operator in operator_map:
                    result[key] = {operator_map[operator]: value}
                else:
                    raise ValueError(f"Unsupported metadata filter operator: {operator}")
            return result

        for key, value in metadata_filters.items():
            if key == "AND":
                # Logical AND: combine multiple conditions
                if not isinstance(value, list):
                    raise ValueError("AND operator requires a list of conditions")
                for condition in value:
                    for sub_key, sub_value in condition.items():
                        processed_filters.update(process_condition(sub_key, sub_value))
            elif key == "OR":
                # Logical OR: Pass through to vector store for implementation-specific handling
                if not isinstance(value, list) or not value:
                    raise ValueError("OR operator requires a non-empty list of conditions")
                # Store OR conditions in a way that vector stores can interpret
                processed_filters["$or"] = []
                for condition in value:
                    or_condition = {}
                    for sub_key, sub_value in condition.items():
                        or_condition.update(process_condition(sub_key, sub_value))
                    processed_filters["$or"].append(or_condition)
            elif key == "NOT":
                # Logical NOT: Pass through to vector store for implementation-specific handling
                if not isinstance(value, list) or not value:
                    raise ValueError("NOT operator requires a non-empty list of conditions")
                processed_filters["$not"] = []
                for condition in value:
                    not_condition = {}
                    for sub_key, sub_value in condition.items():
                        not_condition.update(process_condition(sub_key, sub_value))
                    processed_filters["$not"].append(not_condition)
            else:
                processed_filters.update(process_condition(key, value))

        return processed_filters

    def _has_advanced_operators(self, filters: Dict[str, Any]) -> bool:
        """
        Check if filters contain advanced operators that need special processing.

        Args:
            filters: Dictionary of filters to check

        Returns:
            bool: True if advanced operators are detected
        """
        if not isinstance(filters, dict):
            return False

        for key, value in filters.items():
            # Check for platform-style logical operators
            if key in ["AND", "OR", "NOT"]:
                return True
            # Check for comparison operators (without $ prefix for universal compatibility)
            if isinstance(value, dict):
                for op in value.keys():
                    if op in ["eq", "ne", "gt", "gte", "lt", "lte", "in", "nin", "contains", "icontains"]:
                        return True
            # Check for wildcard values
            if value == "*":
                return True
        return False

    async def search(
            self,
            query: str,
            *,
            user_id: Optional[str] = None,
            agent_id: Optional[str] = None,
            run_id: Optional[str] = None,
            limit: int = 100,
            filters: Optional[Dict[str, Any]] = None,
            threshold: Optional[float] = None,
            metadata_filters: Optional[Dict[str, Any]] = None,
            rerank: bool = True,
    ):
        """
        Searches for memories based on a query
        Args:
            query (str): Query to search for.
            user_id (str, optional): ID of the user to search for. Defaults to None.
            agent_id (str, optional): ID of the agent to search for. Defaults to None.
            run_id (str, optional): ID of the run to search for. Defaults to None.
            limit (int, optional): Limit the number of results. Defaults to 100.
            filters (dict, optional): Legacy filters to apply to the search. Defaults to None.
            threshold (float, optional): Minimum score for a memory to be included in the results. Defaults to None.
            filters (dict, optional): Enhanced metadata filtering with operators:
                - {"key": "value"} - exact match
                - {"key": {"eq": "value"}} - equals
                - {"key": {"ne": "value"}} - not equals
                - {"key": {"in": ["val1", "val2"]}} - in list
                - {"key": {"nin": ["val1", "val2"]}} - not in list
                - {"key": {"gt": 10}} - greater than
                - {"key": {"gte": 10}} - greater than or equal
                - {"key": {"lt": 10}} - less than
                - {"key": {"lte": 10}} - less than or equal
                - {"key": {"contains": "text"}} - contains text
                - {"key": {"icontains": "text"}} - case-insensitive contains
                - {"key": "*"} - wildcard match (any value)
                - {"AND": [filter1, filter2]} - logical AND
                - {"OR": [filter1, filter2]} - logical OR
                - {"NOT": [filter1]} - logical NOT

        Returns:
            dict: A dictionary containing the search results, typically under a "results" key,
                  and potentially "relations" if graph store is enabled.
                  Example for v1.1+: `{"results": [{"id": "...", "memory": "...", "score": 0.8, ...}]}`
        """

        _, effective_filters = _build_filters_and_metadata(
            user_id=user_id, agent_id=agent_id, run_id=run_id, input_filters=filters
        )

        if not any(key in effective_filters for key in ("user_id", "agent_id", "run_id")):
            raise ValueError("at least one of 'user_id', 'agent_id', or 'run_id' must be specified ")

        # Apply enhanced metadata filtering if advanced operators are detected
        if filters and self._has_advanced_operators(filters):
            processed_filters = self._process_metadata_filters(filters)
            effective_filters.update(processed_filters)
        elif filters:
            # Simple filters, merge directly
            effective_filters.update(filters)

        keys, encoded_ids = process_telemetry_filters(effective_filters)
        capture_event(
            "mem0.search",
            self,
            {
                "limit": limit,
                "version": self.api_version,
                "keys": keys,
                "encoded_ids": encoded_ids,
                "sync_type": "async",
                "threshold": threshold,
                "advanced_filters": bool(filters and self._has_advanced_operators(filters)),
            },
        )

        vector_store_task = asyncio.create_task(self._search_vector_store(query, effective_filters, limit, threshold, rerank))

        graph_task = None
        if self.enable_graph:
            if hasattr(self.graph.search, "__await__"):  # Check if graph search is async
                graph_task = asyncio.create_task(self.graph.search(query, effective_filters, limit))
            else:
                graph_task = asyncio.create_task(asyncio.to_thread(self.graph.search, query, effective_filters, limit))

        if graph_task:
            original_memories, graph_entities = await asyncio.gather(vector_store_task, graph_task)
        else:
            original_memories = await vector_store_task
            graph_entities = None

        if self.enable_graph:
            return {"long_term_memory_layered": original_memories, "relations": graph_entities}

        return original_memories

    async def update(self, memory_id, data):
        """
        Update a memory by ID asynchronously.

        Args:
            memory_id (str): ID of the memory to update.
            data (str): New content to update the memory with.

        Returns:
            dict: Success message indicating the memory was updated.

        Example:
            >>> await m.update(memory_id="mem_123", data="Likes to play tennis on weekends")
            {'message': 'Memory updated successfully!'}
        """
        capture_event("mem0.update", self, {"memory_id": memory_id, "sync_type": "async"})

        embeddings = await asyncio.to_thread(self.embedding_model.embed, data, "update")
        existing_embeddings = {data: embeddings}

        await self._update_memory(memory_id, data, existing_embeddings)
        return {"message": "Memory updated successfully!"}

    async def delete(self, memory_id):
        """
        Delete a memory by ID asynchronously.

        Args:
            memory_id (str): ID of the memory to delete.
        """
        capture_event("mem0.delete", self, {"memory_id": memory_id, "sync_type": "async"})
        await self._delete_memory(memory_id)
        return {"message": "Memory deleted successfully!"}

    async def delete_all(self, user_id=None, agent_id=None, run_id=None):
        """
        Delete all memories asynchronously.

        Args:
            user_id (str, optional): ID of the user to delete memories for. Defaults to None.
            agent_id (str, optional): ID of the agent to delete memories for. Defaults to None.
            run_id (str, optional): ID of the run to delete memories for. Defaults to None.
        """
        filters = {}
        if user_id:
            filters["user_id"] = user_id
        if agent_id:
            filters["agent_id"] = agent_id
        if run_id:
            filters["run_id"] = run_id

        if not filters:
            raise ValueError(
                "At least one filter is required to delete all memories. If you want to delete all memories, use the `reset()` method."
            )

        keys, encoded_ids = process_telemetry_filters(filters)
        capture_event("mem0.delete_all", self, {"keys": keys, "encoded_ids": encoded_ids, "sync_type": "async"})
        memories = await asyncio.to_thread(self.vector_store.list, filters=filters)

        delete_tasks = []
        for memory in memories[0]:
            delete_tasks.append(self._delete_memory(memory.id))

        await asyncio.gather(*delete_tasks)

        logger.info(f"Deleted {len(memories[0])} memories")

        if self.enable_graph:
            await asyncio.to_thread(self.graph.delete_all, filters)

        return {"message": "Memories deleted successfully!"}

    async def history(self, memory_id):
        """
        Get the history of changes for a memory by ID asynchronously.

        Args:
            memory_id (str): ID of the memory to get history for.

        Returns:
            list: List of changes for the memory.
        """
        capture_event("mem0.history", self, {"memory_id": memory_id, "sync_type": "async"})
        return await asyncio.to_thread(self.db.get_history, memory_id)

    async def _create_memory(self, data, existing_embeddings, metadata=None):
        logger.debug(f"Creating memory with {data=}")
        if data in existing_embeddings:
            embeddings = existing_embeddings[data]
        else:
            embeddings = await asyncio.to_thread(self.embedding_model.embed, data, memory_action="add")

        memory_id = str(uuid.uuid4())
        metadata = metadata or {}
        metadata["data"] = data
        metadata["hash"] = hashlib.md5(data.encode()).hexdigest()
        metadata["created_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()

        await asyncio.to_thread(
            self.vector_store.insert,
            vectors=[embeddings],
            ids=[memory_id],
            payloads=[metadata],
        )

        await asyncio.to_thread(
            self.db.add_history,
            memory_id,
            None,
            data,
            "ADD",
            created_at=metadata.get("created_at"),
            actor_id=metadata.get("actor_id"),
            role=metadata.get("role"),
        )

        return memory_id

    async def _create_procedural_memory(self, messages, metadata=None, llm=None, prompt=None):
        """
        Create a procedural memory asynchronously

        Args:
            messages (list): List of messages to create a procedural memory from.
            metadata (dict): Metadata to create a procedural memory from.
            llm (llm, optional): LLM to use for the procedural memory creation. Defaults to None.
            prompt (str, optional): Prompt to use for the procedural memory creation. Defaults to None.
        """
        try:
            from langchain_core.messages.utils import (
                convert_to_messages,  # type: ignore
            )
        except Exception:
            logger.error(
                "Import error while loading langchain-core. Please install 'langchain-core' to use procedural memory."
            )
            raise

        logger.info("Creating procedural memory")

        parsed_messages = [
            {"role": "system", "content": prompt or PROCEDURAL_MEMORY_SYSTEM_PROMPT},
            *messages,
            {"role": "user", "content": "Create procedural memory of the above conversation."},
        ]

        try:
            if llm is not None:
                parsed_messages = convert_to_messages(parsed_messages)
                response = await asyncio.to_thread(llm.invoke, input=parsed_messages)
                procedural_memory = response.content
            else:
                procedural_memory = await asyncio.to_thread(self.llm.generate_response, messages=parsed_messages)
                procedural_memory = remove_code_blocks(procedural_memory)

        except Exception as e:
            logger.error(f"Error generating procedural memory summary: {e}")
            raise

        if metadata is None:
            raise ValueError("Metadata cannot be done for procedural memory.")

        metadata["memory_type"] = MemoryType.PROCEDURAL.value
        embeddings = await asyncio.to_thread(self.embedding_model.embed, procedural_memory, memory_action="add")
        memory_id = await self._create_memory(procedural_memory, {procedural_memory: embeddings}, metadata=metadata)
        capture_event("mem0._create_procedural_memory", self, {"memory_id": memory_id, "sync_type": "async"})

        result = {"results": [{"id": memory_id, "memory": procedural_memory, "event": "ADD"}]}

        return result

    async def _update_memory(self, memory_id, data, existing_embeddings, metadata=None):
        logger.info(f"Updating memory with {data=}")

        try:
            existing_memory = await asyncio.to_thread(self.vector_store.get, vector_id=memory_id)
        except Exception:
            logger.error(f"Error getting memory with ID {memory_id} during update.")
            raise ValueError(f"Error getting memory with ID {memory_id}. Please provide a valid 'memory_id'")

        prev_value = existing_memory.payload.get("data")

        new_metadata = deepcopy(metadata) if metadata is not None else {}

        new_metadata["data"] = data
        new_metadata["hash"] = hashlib.md5(data.encode()).hexdigest()
        new_metadata["created_at"] = existing_memory.payload.get("created_at")
        new_metadata["updated_at"] = datetime.now(pytz.timezone("US/Pacific")).isoformat()

        # Preserve session identifiers from existing memory only if not provided in new metadata
        if "user_id" not in new_metadata and "user_id" in existing_memory.payload:
            new_metadata["user_id"] = existing_memory.payload["user_id"]
        if "agent_id" not in new_metadata and "agent_id" in existing_memory.payload:
            new_metadata["agent_id"] = existing_memory.payload["agent_id"]
        if "run_id" not in new_metadata and "run_id" in existing_memory.payload:
            new_metadata["run_id"] = existing_memory.payload["run_id"]

        if "actor_id" not in new_metadata and "actor_id" in existing_memory.payload:
            new_metadata["actor_id"] = existing_memory.payload["actor_id"]
        if "role" not in new_metadata and "role" in existing_memory.payload:
            new_metadata["role"] = existing_memory.payload["role"]

        if data in existing_embeddings:
            embeddings = existing_embeddings[data]
        else:
            embeddings = await asyncio.to_thread(self.embedding_model.embed, data, "update")

        await asyncio.to_thread(
            self.vector_store.update,
            vector_id=memory_id,
            vector=embeddings,
            payload=new_metadata,
        )
        logger.info(f"Updating memory with ID {memory_id=} with {data=}")

        await asyncio.to_thread(
            self.db.add_history,
            memory_id,
            prev_value,
            data,
            "UPDATE",
            created_at=new_metadata["created_at"],
            updated_at=new_metadata["updated_at"],
            actor_id=new_metadata.get("actor_id"),
            role=new_metadata.get("role"),
        )
        return memory_id

    async def _delete_memory(self, memory_id):
        logger.info(f"Deleting memory with {memory_id=}")
        existing_memory = await asyncio.to_thread(self.vector_store.get, vector_id=memory_id)
        prev_value = existing_memory.payload.get("data", "")

        await asyncio.to_thread(self.vector_store.delete, vector_id=memory_id)
        await asyncio.to_thread(
            self.db.add_history,
            memory_id,
            prev_value,
            None,
            "DELETE",
            actor_id=existing_memory.payload.get("actor_id"),
            role=existing_memory.payload.get("role"),
            is_deleted=1,
        )

        return memory_id

    async def reset(self):
        """
        Reset the memory store asynchronously by:
            Deletes the vector store collection
            Resets the database
            Recreates the vector store with a new client
        """
        logger.warning("Resetting all memories")
        await asyncio.to_thread(self.vector_store.delete_col)

        gc.collect()

        if hasattr(self.vector_store, "client") and hasattr(self.vector_store.client, "close"):
            await asyncio.to_thread(self.vector_store.client.close)

        if hasattr(self.db, "connection") and self.db.connection:
            await asyncio.to_thread(lambda: self.db.connection.execute("DROP TABLE IF EXISTS history"))
            await asyncio.to_thread(self.db.connection.close)

        self.db = SQLiteManager(self.config.history_db_path)

        self.vector_store = VectorStoreFactory.create(
            self.config.vector_store.provider, self.config.vector_store.config
        )
        capture_event("mem0.reset", self, {"sync_type": "async"})

    async def chat(self, query):
        raise NotImplementedError("Chat function not implemented yet.")

