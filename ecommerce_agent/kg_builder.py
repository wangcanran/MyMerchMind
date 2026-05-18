"""
服装知识图谱构建器
使用 LightRAG 从小红书数据构建知识图谱
"""
import asyncio
import json
import os
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

# LightRAG imports（首次加载可能较慢，避免误以为进程无响应）
import sys

# 使用项目内的 LightRAG 子目录（与 kg_builder 同级的 LightRAG/）
sys.path.insert(0, str(Path(__file__).resolve().parent / "LightRAG"))

print("正在导入 LightRAG 等依赖（首次或冷启动可能需数十秒）…", flush=True)

from lightrag import LightRAG, QueryParam
from lightrag.llm.openai import openai_complete_if_cache, openai_embed
from lightrag.utils import EmbeddingFunc

try:
    from config import settings
except ModuleNotFoundError:
    from types import SimpleNamespace

    try:
        from .llm.config import load_llm_config

        _lc = load_llm_config()
        _openai_key = _lc.api_key
        _openai_model = _lc.model
        _openai_base = _lc.base_url.rstrip("/")
    except Exception:
        _openai_key = (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or "").strip()
        _openai_model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        _openai_base = (
            os.environ.get("LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")

    settings = SimpleNamespace(
        llm_provider=os.environ.get("LLM_PROVIDER", "openai").strip().lower(),
        openai_model=_openai_model,
        openai_api_key=_openai_key,
        openai_base_url=_openai_base,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL", ""),
        lightrag_entity_types_file=os.environ.get("LIGHTRAG_ENTITY_TYPES_FILE", ""),
        embedding_timeout_sec=int(os.environ.get("EMBEDDING_TIMEOUT_SEC", "180")),
        embedding_func_max_async=int(os.environ.get("EMBEDDING_FUNC_MAX_ASYNC", "4")),
        kg_engagement_doc_mode=os.environ.get("KG_ENGAGEMENT_DOC_MODE", "tier"),
        lightrag_language=os.environ.get("LIGHTRAG_LANGUAGE", "Simplified Chinese"),
        llm_timeout_sec=float(os.environ.get("LLM_TIMEOUT_SEC", os.environ.get("LLM_TIMEOUT_S", "180"))),
        embedding_api_key=(os.environ.get("LIGHTRAG_EMBED_API_KEY") or "").strip(),
        embedding_base_url=(os.environ.get("LIGHTRAG_EMBED_BASE_URL") or "").strip(),
        embedding_model=(
            (os.environ.get("LIGHTRAG_EMBED_MODEL") or "").strip() or "text-embedding-3-small"
        ),
    )


def resolve_lightrag_embedding_config(
    llm_key: str,
    llm_base: Optional[str],
) -> Tuple[str, str, str, bool]:
    """
    LightRAG 嵌入所用 OpenAI 兼容接口（可与抽取/问答用的 LLM 不同网关）。

    若配置了 ``embedding_api_key`` + ``embedding_base_url``（或环境变量
    ``LIGHTRAG_EMBED_API_KEY`` + ``LIGHTRAG_EMBED_BASE_URL``），则仅嵌入请求发往该地址
    （例如 4zapi）；聊天仍由 ``_llm_config()`` 决定。

    未配置独立嵌入时：沿用旧逻辑——优先 ``openai_api_key``；否则与 LLM 共用一对 key/base。

    Returns:
        (api_key, base_url, embed_model, dedicated_gateway)
    """
    s = settings
    key = (
        (getattr(s, "embedding_api_key", None) or "").strip()
        or (os.environ.get("LIGHTRAG_EMBED_API_KEY") or "").strip()
        or (os.environ.get("LIGHTRAG_EMBEDDING_API_KEY") or "").strip()
    )
    base = (
        (getattr(s, "embedding_base_url", None) or "").strip()
        or (os.environ.get("LIGHTRAG_EMBED_BASE_URL") or "").strip()
        or (os.environ.get("LIGHTRAG_EMBEDDING_BASE_URL") or "").strip()
    )
    model = (
        (getattr(s, "embedding_model", None) or "").strip()
        or (os.environ.get("LIGHTRAG_EMBED_MODEL") or "").strip()
        or "text-embedding-3-small"
    )

    if key and base:
        return key, base.rstrip("/"), model, True

    oa = (getattr(s, "openai_api_key", None) or "").strip()
    if oa:
        ob = getattr(s, "openai_base_url", None) or llm_base or ""
        return oa, str(ob).rstrip("/"), model, False

    return llm_key, (llm_base or "").rstrip("/"), model, False


def _coerce_int_like(v: Any, default: int = 0) -> int:
    """将赞/藏字段尽量转为 int（兼容少量字符串如「1.2万」则保守按 default）。"""
    if v is None:
        return default
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v).strip()
    if not s:
        return default
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def engagement_sentence_for_kg_doc(liked: Any, collected: Any) -> str:
    """
    生成写入 LightRAG 入库正文的互动描述。

    由 ``settings.kg_engagement_doc_mode`` 控制：tier / exact / omit。
    tier 使用少数固定档位句，避免「每条数字不同」在抽取阶段产生大量无意义数字实体。
    """
    mode = (getattr(settings, "kg_engagement_doc_mode", None) or "tier").strip().lower()
    if mode == "omit":
        return ""
    lk = _coerce_int_like(liked, 0)
    cl = _coerce_int_like(collected, 0)
    if lk <= 0 and cl <= 0:
        return ""
    if mode == "exact":
        return f"互动量约点赞{lk}、收藏{cl}，仅作热度参考。\n\n"
    # tier：综合分粗略分档（阈值可按业务再调）
    score = lk + cl * 2
    if lk >= 5000 or score >= 8000:
        tier = "互动热度很高"
    elif lk >= 1000 or score >= 2000:
        tier = "互动热度较高"
    elif lk >= 200 or score >= 400:
        tier = "互动热度中等"
    else:
        tier = "互动热度一般"
    return f"{tier}（帖级赞藏为相对档位，非精确数；运营统计请以原始 JSON 为准）。\n\n"


def _cap_openai_nonstream_max_tokens(kwargs: Dict[str, Any]) -> None:
    """
    部分 OpenAI 兼容网关（如 Gitee AI）要求：非流式请求若 max_tokens > 4096 则必须 stream=true。

    LightRAG 在关键词抽取等路径可能不显式传 max_tokens，底层会使用较大默认值从而触发 400。
    在非 stream 模式下将输出上限钳制到 4096（可用 LLM_MAX_OUTPUT_TOKENS / LIGHTRAG_LLM_MAX_TOKENS 调小，仍不超过 4096）。
    """
    if kwargs.get("stream"):
        return
    try:
        raw = int(
            os.environ.get(
                "LIGHTRAG_LLM_MAX_TOKENS",
                os.environ.get("LLM_MAX_OUTPUT_TOKENS", "4096"),
            )
        )
    except ValueError:
        raw = 4096
    cap = max(1, min(raw, 4096))
    for key in ("max_tokens", "max_completion_tokens"):
        if key not in kwargs or kwargs[key] is None:
            continue
        try:
            v = int(kwargs[key])
            kwargs[key] = max(1, min(v, 4096))
        except (TypeError, ValueError):
            kwargs.pop(key, None)
    if kwargs.get("max_tokens") is None and kwargs.get("max_completion_tokens") is None:
        kwargs["max_tokens"] = cap


class ClothingKnowledgeGraph:
    """服装知识图谱构建和查询"""

    def __init__(self, working_dir: str = "kg_storage"):
        """
        初始化知识图谱

        Args:
            working_dir: 知识图谱存储目录
        """
        self.working_dir = working_dir
        self.rag = None
        # 本次入库的 JSON 相对路径（POSIX），供 LightRAG file_path 溯源到具体文件
        self._source_json_posix: Optional[str] = None

        # 确保目录存在
        os.makedirs(working_dir, exist_ok=True)

    @staticmethod
    def _llm_config():
        """与 config.Settings 对齐：按 llm_provider 取模型名与 API。"""
        p = (settings.llm_provider or "anthropic").strip().lower()
        if p == "openai":
            return (
                settings.openai_model,
                settings.openai_api_key,
                settings.openai_base_url,
            )
        return (
            settings.anthropic_model,
            settings.anthropic_api_key,
            settings.anthropic_base_url,
        )

    @staticmethod
    def load_lightrag_entity_schema_bundle() -> tuple[Optional[List[str]], str]:
        """
        从 ``settings.lightrag_entity_types_file`` 加载实体类型白名单与抽取用边界定义正文。

        Returns:
            (entity_types 或 None, entity_type_definitions 拼入抽取 system prompt 的字符串，可为空)

        支持：
        - JSON 对象：``entity_types`` 数组；可选 ``type_boundary_rules``（总边界）、
          ``entity_type_definitions``（类型名 -> 单行释义，按 entity_types 顺序输出）。
        - 顶层 JSON 数组：仅类型列表，定义为空。
        """
        rel = (getattr(settings, "lightrag_entity_types_file", None) or "").strip()
        if not rel:
            return None, ""
        path = (Path(__file__).resolve().parent / rel).resolve()
        if not path.is_file():
            print(
                f"提示: 未找到实体类型文件 {path}，将使用 LightRAG 默认 entity_types。",
                flush=True,
            )
            return None, ""
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告: 无法读取实体类型文件 {path}: {e}，使用默认类型。", flush=True)
            return None, ""

        types_out: Optional[List[str]] = None
        if isinstance(data, dict) and isinstance(data.get("entity_types"), list):
            types_out = [str(x).strip() for x in data["entity_types"] if str(x).strip()]
            types_out = types_out or None
        elif isinstance(data, list):
            types_out = [str(x).strip() for x in data if str(x).strip()]
            types_out = types_out or None
        elif isinstance(data, dict):
            print(
                f"警告: {path} 为对象但缺少 entity_types 数组。",
                flush=True,
            )

        def_lines: List[str] = []
        if isinstance(data, dict):
            br = data.get("type_boundary_rules")
            if isinstance(br, str) and br.strip():
                def_lines.append(br.strip())
            per = data.get("entity_type_definitions")
            if isinstance(per, dict):
                if types_out:
                    def_lines.append("【各类型释义】")
                    for t in types_out:
                        rule = per.get(t)
                        if isinstance(rule, str) and rule.strip():
                            def_lines.append(f"- {t}：{rule.strip()}")
                else:
                    def_lines.append("【各类型释义】")
                    for k, v in per.items():
                        if str(k).startswith("_"):
                            continue
                        if isinstance(v, str) and v.strip():
                            def_lines.append(f"- {k}：{v.strip()}")

        def_text = "\n".join(def_lines).strip()
        return types_out, def_text

    async def initialize(self):
        """初始化 LightRAG"""
        print("正在初始化知识图谱...", flush=True)

        llm_name, llm_key, llm_base = self._llm_config()
        emb_key, emb_base, emb_model, emb_dedicated = resolve_lightrag_embedding_config(
            llm_key, llm_base
        )
        if emb_dedicated:
            print(
                f"嵌入使用独立网关: {emb_base}（模型 {emb_model}）；抽取/问答 LLM 仍为 {llm_name}。",
                flush=True,
            )

        emb_timeout = int(getattr(settings, "embedding_timeout_sec", 180))
        emb_max_async = int(getattr(settings, "embedding_func_max_async", 4))

        async def embed_func(texts: List[str]):
            # openai_embed 不接受 timeout=；HTTP 超时通过 client_configs 传给底层 AsyncOpenAI
            return await openai_embed(
                texts,
                model=emb_model,
                api_key=emb_key,
                base_url=emb_base,
                client_configs={"timeout": float(emb_timeout)},
            )

        # LightRAG 调用约定：llm_model_func(prompt, system_prompt=..., **kwargs)
        # openai_complete_if_cache 签名为 (model, prompt, ...)，不能直接当 llm_model_func 传入
        async def llm_adapter(
            prompt: str,
            system_prompt=None,
            history_messages=None,
            keyword_extraction: bool = False,
            **kwargs: Any,
        ) -> str:
            kwargs.pop("hashing_kv", None)
            _cap_openai_nonstream_max_tokens(kwargs)
            api_key = kwargs.pop("api_key", llm_key)
            base_url = kwargs.pop("base_url", llm_base)
            timeout = kwargs.pop("timeout", None)
            if timeout is None:
                timeout = int(getattr(settings, "llm_timeout_sec", 180))
            return await openai_complete_if_cache(
                llm_name,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                keyword_extraction=keyword_extraction,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                **kwargs,
            )

        # 图谱抽取与合并摘要语言（LightRAG 注入到 entity_extraction / summary 等 prompt 的 {language}）
        rag_language = (getattr(settings, "lightrag_language", None) or "Simplified Chinese").strip()

        addon_params: Dict[str, Any] = {"language": rag_language}
        entity_types, entity_defs = (
            ClothingKnowledgeGraph.load_lightrag_entity_schema_bundle()
        )
        if entity_types:
            addon_params["entity_types"] = entity_types
            print(
                f"已注入业务实体类型 {len(entity_types)} 项（lightrag_entity_types_file）。",
                flush=True,
            )
        if entity_defs.strip():
            addon_params["entity_type_definitions"] = entity_defs.strip()
            print(
                f"已注入 entity_type 边界定义 {len(entity_defs)} 字符（写入抽取 system prompt）。",
                flush=True,
            )

        if bool(getattr(settings, "lightrag_skip_other_entities_in_graph", False)):
            addon_params["skip_other_entities_in_graph"] = True
            print("已启用：entity_type 为 other 的实体不入图（并跳过相关关系边）。", flush=True)

        if bool(getattr(settings, "lightrag_isolate_other_entity_edges_in_graph", True)):
            addon_params["isolate_other_entity_edges_in_graph"] = True
            if not addon_params.get("skip_other_entities_in_graph"):
                print(
                    "已启用：other 实体入图，但同次抽取中不写入任一端为该 other 名的关系边。",
                    flush=True,
                )

        # 配置 LLM 和 Embedding（与 LightRAG 示例一致：从 lightrag.llm.openai 导入）
        self.rag = LightRAG(
            working_dir=self.working_dir,
            llm_model_func=llm_adapter,
            llm_model_name=llm_name,
            llm_model_max_async=4,
            llm_model_kwargs={
                "api_key": llm_key,
                "base_url": llm_base,
                "timeout": int(getattr(settings, "llm_timeout_sec", 180)),
            },
            addon_params=addon_params,
            default_embedding_timeout=emb_timeout,
            embedding_func_max_async=emb_max_async,
            embedding_func=EmbeddingFunc(
                embedding_dim=1536,
                max_token_size=8192,
                func=embed_func,
            ),
        )

        # 初始化存储
        await self.rag.initialize_storages()
        print(
            f"知识图谱初始化完成（抽取语言: {rag_language}；嵌入超时 {emb_timeout}s，Worker 约 {emb_timeout * 2}s；"
            f"嵌入并发 {emb_max_async}）",
            flush=True,
        )

    async def export_entities_catalog(
        self,
        output_path: Optional[str] = None,
        *,
        sort_by_degree: bool = True,
        description_max_len: int = 240,
    ) -> str:
        """
        导出当前知识图谱中的全部实体到 JSON，便于人工筛选后删除伪实体/枢纽节点。

        每条包含：name（与图中一致，用于 delete_by_entity）、entity_type、
        degree（无向边数，越高越可能是模板超级节点）、description_preview。

        Returns:
            写入的 JSON 文件绝对路径或项目相对路径（与传入 output_path 一致）。
        """
        if not self.rag:
            await self.initialize()

        graph = self.rag.chunk_entity_relation_graph
        nodes = await graph.get_all_nodes()
        edges = await graph.get_all_edges()
        deg: Counter[str] = Counter()
        for e in edges:
            s, t = e.get("source"), e.get("target")
            if s:
                deg[str(s)] += 1
            if t:
                deg[str(t)] += 1

        rows: List[Dict[str, Any]] = []
        for n in nodes:
            name = str(n.get("id") or n.get("entity_id") or "").strip()
            if not name:
                continue
            et = str(n.get("entity_type", "") or "")
            desc = str(n.get("description") or "").strip()
            if len(desc) > description_max_len:
                desc = desc[: description_max_len - 3] + "..."
            rows.append(
                {
                    "name": name,
                    "entity_type": et,
                    "degree": int(deg.get(name, 0)),
                    "description_preview": desc,
                }
            )

        if sort_by_degree:
            rows.sort(key=lambda r: (-r["degree"], r["name"]))
        else:
            rows.sort(key=lambda r: r["name"])

        out = output_path or str(Path(self.working_dir) / "entities_catalog.json")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "working_dir": self.working_dir,
            "entity_count": len(rows),
            "entities": rows,
            "delete_hint": (
                "在已初始化 storages 的 LightRAG 实例上调用："
                "await rag.adelete_by_entity(\"实体名\") 或 rag.delete_by_entity(\"实体名\")；"
                "名称须与本文件中的 name 完全一致。"
            ),
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        print(
            f"\n已导出实体目录（共 {len(rows)} 个）: {out}\n"
            "  默认按度数从高到低排序，便于发现模板类枢纽；"
            "从 JSON 里复制要删的 name，再调用 delete_by_entity。",
            flush=True,
        )
        return out

    @staticmethod
    def _read_entity_names_file(path: str) -> List[str]:
        """每行一个实体名；空行与 ``#`` 开头行为注释。"""
        raw = Path(path).read_text(encoding="utf-8-sig")
        names: List[str] = []
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            names.append(s)
        return names

    @staticmethod
    def _read_relation_pairs_file(path: str) -> List[tuple[str, str]]:
        """
        每行一条无向边：``实体A<TAB>实体B``（中间为制表符）。
        无向图中两端顺序任意，LightRAG 内部会规范化。
        """
        raw = Path(path).read_text(encoding="utf-8-sig")
        pairs: List[tuple[str, str]] = []
        for i, line in enumerate(raw.splitlines(), start=1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "\t" not in s:
                raise ValueError(
                    f"第 {i} 行：关系必须用 TAB 分隔两个实体名，当前行: {s[:120]!r}"
                )
            left, right = s.split("\t", 1)
            a, b = left.strip(), right.strip()
            if not a or not b:
                raise ValueError(f"第 {i} 行：两端实体名均不能为空: {s[:120]!r}")
            pairs.append((a, b))
        return pairs

    async def delete_entities_by_names(self, names: List[str]) -> None:
        """
        按名称删除实体及其关联的全部边，并同步更新实体/关系向量库（LightRAG 内置逻辑）。

        ``names`` 须与 ``entities_catalog.json`` 里的 ``name`` 或图中的节点 id 完全一致。
        """
        if not self.rag:
            await self.initialize()
        for name in names:
            r = await self.rag.adelete_by_entity(name)
            label = "✓" if r.status == "success" else ("○" if r.status == "not_found" else "✗")
            print(f"  {label} 删除实体 `{name}`: {r.message}", flush=True)

    async def delete_relations_by_pairs(self, pairs: List[tuple[str, str]]) -> None:
        """
        仅删除两实体之间的边（两个节点仍保留）；同步更新关系向量库。

        ``pairs`` 每项为 ``(实体A, 实体B)``，与图中存的边一致即可（无向，顺序不限）。
        """
        if not self.rag:
            await self.initialize()
        for a, b in pairs:
            r = await self.rag.adelete_by_relation(a, b)
            label = "✓" if r.status == "success" else ("○" if r.status == "not_found" else "✗")
            print(f"  {label} 删除边 `{a}` ~ `{b}`: {r.message}", flush=True)

    async def build_from_posts(
        self,
        posts: List[Dict],
        batch_size: int = 10,
        source_json: Optional[str] = None,
        *,
        export_entities_after_build: bool = True,
        entities_catalog_path: Optional[str] = None,
    ):
        """
        从小红书帖子数据构建知识图谱

        Args:
            posts: 帖子数据列表
            batch_size: 批处理大小
            source_json: 本次入库的 JSON 文件路径；传入后 LightRAG 的 file_path 可溯源到
                如 crawlers/clothing_data/clothing_posts_20260417_005028_annotated.json
            export_entities_after_build: 构建结束后是否导出全部实体列表（JSON）
            entities_catalog_path: 导出路径，默认 ``<working_dir>/entities_catalog.json``
        """
        if not self.rag:
            await self.initialize()

        self._source_json_posix = (
            self._normalize_source_json_path(source_json) if source_json else None
        )
        if self._source_json_posix:
            print(
                f"溯源前缀（file_path）: {self._source_json_posix}/<记录id>",
                flush=True,
            )

        print(f"\n开始构建知识图谱，共 {len(posts)} 条记录", flush=True)

        # 将帖子转换为文本文档（数据量大时仅本步就可能很久）
        documents = []
        doc_ids = []
        file_paths: List[str] = []
        n_posts = len(posts)
        progress_every = max(500, n_posts // 20) if n_posts > 1000 else 0

        for idx, post in enumerate(posts):
            doc_text = self._post_to_document(post)
            documents.append(doc_text)
            doc_ids.append(self._doc_id_for_record(post))
            file_paths.append(self._file_path_for_record(post))
            if progress_every and (idx + 1) % progress_every == 0:
                print(
                    f"  文档转换进度: {idx + 1}/{n_posts}",
                    flush=True,
                )

        # 批量插入
        total_batches = (len(documents) + batch_size - 1) // batch_size

        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            batch_ids = doc_ids[i:i + batch_size]
            batch_paths = file_paths[i:i + batch_size]

            batch_num = i // batch_size + 1
            print(f"处理批次 {batch_num}/{total_batches}...", flush=True)

            try:
                await self.rag.ainsert(
                    batch,
                    ids=batch_ids,
                    file_paths=batch_paths,
                )
                print(f"  ✓ 批次 {batch_num} 完成", flush=True)
            except Exception as e:
                print(f"  ✗ 批次 {batch_num} 失败: {e}")

        print("\n知识图谱构建完成！")
        if export_entities_after_build:
            try:
                await self.export_entities_catalog(output_path=entities_catalog_path)
            except Exception as e:
                print(f"  警告: 导出实体目录失败（可稍后手动调用 export_entities_catalog）: {e}", flush=True)
        self._source_json_posix = None

    @staticmethod
    def _normalize_source_json_path(json_path: str) -> str:
        """
        将用户传入的 JSON 路径转为相对当前工作目录的 POSIX 路径，
        便于在引用里直接对应 crawlers/clothing_data/xxx.json。
        """
        p = Path(json_path).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        else:
            p = p.resolve()
        try:
            rel = p.relative_to(Path.cwd().resolve())
            return rel.as_posix()
        except ValueError:
            return p.as_posix()

    @staticmethod
    def _doc_id_for_record(post: Dict) -> str:
        """爬虫帖子用 post_id；标注穿搭记录用 id。"""
        pid = post.get("post_id")
        if pid is not None and str(pid).strip():
            return str(pid)
        oid = post.get("id")
        if oid is not None and str(oid).strip():
            return str(oid)
        return ""

    @staticmethod
    def _crawl_batch_key(post: Dict) -> str:
        """
        从 crawl_time 抽出批次段，区分不同期爬虫/不同月份合并进同一库时的来源。
        优先 post_info.crawl_time（标注记录），否则顶层 crawl_time；格式取 ISO 的 YYYY-MM。
        """
        ct: Any = None
        pi = post.get("post_info")
        if isinstance(pi, dict):
            ct = pi.get("crawl_time")
        if not ct:
            ct = post.get("crawl_time")
        if not ct:
            return "unknown_batch"
        s = str(ct).strip()
        for sep in ("T", " "):
            if sep in s:
                s = s.split(sep, 1)[0]
                break
        # 期望 ISO 日期前缀 YYYY-MM-DD 或 YYYY-MM，统一取前 7 位为「按月批次」
        if len(s) >= 7 and s[4] == "-":
            return s[:7]
        return "unknown_batch"

    def _file_path_for_record(self, post: Dict) -> str:
        """
        传给 LightRAG 的 citation 来源。
        若 build_from_posts 传入了 source_json，则 file_path 为「该 JSON 相对路径/记录 id」，
        可直接对应 crawlers/clothing_data/clothing_posts_xxx_annotated.json。
        否则退化为按 crawl_time 月批次的路径。
        """
        batch = ClothingKnowledgeGraph._crawl_batch_key(post)
        base = getattr(self, "_source_json_posix", None)

        def _tail_annotated() -> str:
            rid = post.get("id")
            if rid is not None and str(rid).strip():
                return str(rid).strip()
            sid = str(post.get("source_post_id") or "").strip()
            oix = post.get("outfit_index", "")
            return f"{sid}_outfit_{oix}" if sid else f"outfit_{oix}"

        def _tail_crawler() -> str:
            pid = post.get("post_id")
            if pid is not None and str(pid).strip():
                return str(pid).strip()
            oid = post.get("id")
            if oid is not None and str(oid).strip():
                return str(oid).strip()
            return "no_id"

        if base:
            if ClothingKnowledgeGraph._is_annotated_outfit_record(post):
                return f"{base}/{_tail_annotated()}"
            return f"{base}/{_tail_crawler()}"

        if ClothingKnowledgeGraph._is_annotated_outfit_record(post):
            return f"annotated/{batch}/{_tail_annotated()}"

        tail = _tail_crawler()
        if tail != "no_id":
            return f"crawler/{batch}/{tail}"
        return f"kg_builder/{batch}/no_id"

    @staticmethod
    def _is_annotated_outfit_record(post: Dict) -> bool:
        """tag_annotation 输出的穿搭级 JSON（含 post_info + outfit + attributes）。"""
        return (
            isinstance(post.get("post_info"), dict)
            and isinstance(post.get("outfit"), dict)
            and isinstance(post.get("attributes"), dict)
            and post.get("source_post_id") is not None
        )

    @staticmethod
    def _cooccurrence_bucket_fallback(category: str) -> str:
        """
        无 `garment_slot` 时，用 category 子串粗分上装/下装/鞋（兜底）。
        包、表、帽、饰等小物返回空串，不参与衣–衣共现句。
        """
        c = (category or "").strip()
        if not c:
            return ""
        if any(
            x in c
            for x in (
                "包",
                "表",
                "耳饰",
                "耳钉",
                "项链",
                "手链",
                "戒指",
                "袜",
                "腰带",
                "帽",
                "围巾",
                "墨镜",
                "眼镜",
            )
        ):
            return ""
        if any(
            x in c
            for x in (
                "运动鞋",
                "帆布鞋",
                "板鞋",
                "凉鞋",
                "拖鞋",
                "短靴",
                "长靴",
                "靴子",
                "球鞋",
                "乐福鞋",
                "高跟鞋",
                "平底鞋",
            )
        ):
            return "shoe"
        if c.endswith("鞋") or "靴" in c:
            return "shoe"
        if any(
            x in c
            for x in (
                "裤",
                "裙",
                "短裤",
                "长裤",
                "阔腿裤",
                "牛仔裤",
                "西裤",
                "卫裤",
                "工装裤",
                "半裙",
                "连衣裙",
            )
        ):
            return "bottom"
        if any(
            x in c
            for x in (
                "衣",
                "衫",
                "T恤",
                "卫衣",
                "外套",
                "夹克",
                "大衣",
                "西装",
                "西服",
                "毛衣",
                "针织",
                "背心",
                "吊带",
                "Polo",
                "开衫",
                "马甲",
                "罩衫",
                "雪纺",
            )
        ):
            return "top"
        return ""

    @staticmethod
    def _cooccurrence_slot_from_item(item: Dict) -> str:
        """
        优先使用标注/视觉分析写入的 garment_slot；缺失或无法识别时再走 category 兜底。

        约定取值（大小写不敏感）：
        - 上装: top, upper, 上装
        - 下装: bottom, lower, 下装
        - 鞋: shoe, shoes, footwear, 鞋, 鞋类
        - 不参与共现边: accessory, accessories, 配饰, other, none, skip, 忽略 等
        """
        if not isinstance(item, dict):
            return ""
        raw = item.get("garment_slot")
        if raw is not None and str(raw).strip():
            s = str(raw).strip().lower()
            slot_map = {
                "top": "top",
                "upper": "top",
                "上装": "top",
                "tops": "top",
                "bottom": "bottom",
                "lower": "bottom",
                "下装": "bottom",
                "bottoms": "bottom",
                "shoe": "shoe",
                "shoes": "shoe",
                "footwear": "shoe",
                "鞋": "shoe",
                "鞋类": "shoe",
            }
            if s in slot_map:
                return slot_map[s]
            if s in (
                "accessory",
                "accessories",
                "配饰",
                "other",
                "none",
                "skip",
                "忽略",
                "包",
            ):
                return ""
            # 未知取值：退回 category 启发，避免静默丢边
        return ClothingKnowledgeGraph._cooccurrence_bucket_fallback(
            (item.get("category") or "").strip()
        )

    @staticmethod
    def _cooccurrence_edges_paragraph(post: Dict, max_lines: int = 24) -> str:
        """
        从顶层 items 生成短句，诱导图谱中出现「衣–衣」边（上装↔下装、下装↔鞋），
        不做全两两组合；句式尽量短，避免模板尾语被误抽成实体。
        """
        items = post.get("items")
        if not isinstance(items, list) or len(items) < 2:
            return ""

        tops: List[str] = []
        bottoms: List[str] = []
        shoes: List[str] = []

        for it in items:
            if not isinstance(it, dict):
                continue
            cat = (it.get("category") or "").strip()
            if not cat:
                continue
            b = ClothingKnowledgeGraph._cooccurrence_slot_from_item(it)
            if b == "top":
                tops.append(cat)
            elif b == "bottom":
                bottoms.append(cat)
            elif b == "shoe":
                shoes.append(cat)

        def _dedupe(seq: List[str]) -> List[str]:
            seen: set[str] = set()
            out: List[str] = []
            for x in seq:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        tops, bottoms, shoes = _dedupe(tops), _dedupe(bottoms), _dedupe(shoes)
        lines: List[str] = []
        for t in tops:
            for b in bottoms:
                lines.append(f"{t}和{b}出现在同一套穿搭里。")
                if len(lines) >= max_lines:
                    return "\n" + "\n".join(lines) + "\n\n"
        for b in bottoms:
            for s in shoes:
                lines.append(f"{b}和{s}出现在同一套穿搭里。")
                if len(lines) >= max_lines:
                    return "\n" + "\n".join(lines) + "\n\n"

        if not lines:
            return ""
        return "\n" + "\n".join(lines) + "\n\n"

    def _synthetic_image_analysis_from_annotated(self, post: Dict) -> Dict:
        """
        将标注记录中的 attributes/items/context 转为与 _format_image_analysis 兼容的结构。
        attributes.colors 可能是 dict（primary/secondary/combination）或旧版 list。
        """
        attrs = post.get("attributes") or {}
        ctx = post.get("context") or {}
        colors = attrs.get("colors")
        color_scheme: Dict = {}
        if isinstance(colors, dict) and colors:
            sec = colors.get("secondary")
            if not isinstance(sec, list):
                sec = []
            color_scheme = {
                "primary": colors.get("primary") or "",
                "secondary": sec,
                "combination": colors.get("combination") or "",
            }
        elif isinstance(colors, list) and colors:
            color_scheme = {
                "primary": "",
                "secondary": colors,
                "combination": "",
            }

        syn: Dict = {
            "categories": list(attrs.get("categories") or []),
            "items": list(post.get("items") or []),
            "overall_style": list(attrs.get("styles") or []),
            "seasons": list(ctx.get("season") or []),
            "occasions": list(ctx.get("occasion") or []),
            "body_types": list(attrs.get("body_types") or []),
        }
        if color_scheme and (
            color_scheme.get("primary")
            or color_scheme.get("secondary")
            or color_scheme.get("combination")
        ):
            syn["color_scheme"] = color_scheme
        return syn

    @staticmethod
    def _post_info_time_lines(crawl_time: str) -> str:
        """以数据爬取时间作为语境时效与溯源参照（本地采集时间）。"""
        if not crawl_time:
            return ""
        return (
            f"- 数据爬取时间: {crawl_time}（仅作批次语境与溯源；不按该时间生成衣著类目方面的节点）\n"
            "- 可与季节、场景类标签对照理解相对新旧。\n"
        )

    @staticmethod
    def _merchandising_kg_intro() -> str:
        """入库正文不写规则段：范围与语言由 LightRAG addon_params 与抽取框架处理。"""
        return ""

    @staticmethod
    def _context_dim_phrase(label: str, joined: str) -> str:
        """避免「常见场景为无」等整串被误抽成实体；无标签时不写「为无」。"""
        j = (joined or "").strip()
        if not j or j == "无":
            return f"{label}未单独标注"
        return f"{label}包括{j}"

    def _annotated_outfit_to_document(self, post: Dict) -> str:
        """标注模块输出的单套穿搭记录 → 供 LightRAG 抽取实体与关系。"""
        ctx = post.get("context") or {}
        outfit = post.get("outfit") or {}
        attrs = post.get("attributes") or {}
        # 不在正文写 annotation_status（英文 ok 等易被抽成无意义实体，如 Merged: `Ok`）
        otot = post.get("outfit_total", "")
        try:
            otot_n = int(otot) if otot not in (None, "") else 1
        except (TypeError, ValueError):
            otot_n = 1
        # 多图一帖时，整图综述与图像 tags 在每套记录里重复，易放大「小红书/标题」等噪声
        single_outfit_post = otot_n <= 1

        # 入库只保留选品信号；溯源由 doc_id 与 ainsert 的 file_path 承担。
        doc = self._merchandising_kg_intro()
        season_s = "、".join(ctx.get("season") or []) or "无"
        weather_s = "、".join(ctx.get("weather") or []) or "无"
        temp_s = "、".join(ctx.get("temperature") or []) or "无"
        occ_s = "、".join(ctx.get("occasion") or []) or "无"
        # 不写「语境」等小标题，避免被整段抽成节点（如「穿搭语境」）
        doc += (
            "，".join(
                [
                    self._context_dim_phrase("季节", season_s),
                    self._context_dim_phrase("天气", weather_s),
                    self._context_dim_phrase("温度", temp_s),
                    self._context_dim_phrase("场景", occ_s),
                ]
            )
            + "。\n\n"
        )

        desc = (outfit.get("description") or "").strip()
        if desc:
            doc += f"{desc}\n\n"

        mats = attrs.get("materials")
        if isinstance(mats, list) and mats:
            doc += f"涉及材质包括{'、'.join(mats)}。\n\n"

        syn = self._synthetic_image_analysis_from_annotated(post)
        doc += self._format_image_analysis(syn)
        doc += self._cooccurrence_edges_paragraph(post)

        rd = post.get("raw_data") or {}
        ia = rd.get("image_analysis") if isinstance(rd.get("image_analysis"), dict) else {}
        if single_outfit_post:
            if ia.get("outfit_combination"):
                doc += f"{ia['outfit_combination']}\n\n"
            if ia.get("tags"):
                doc += f"图像侧常见{', '.join(ia['tags'])}。\n\n"

        tt = rd.get("text_tags")
        if isinstance(tt, dict) and tt:
            parts = []
            for k, v in tt.items():
                if isinstance(v, list) and v:
                    parts.append(f"{k} 为 {'、'.join(str(x) for x in v)}")
                elif v not in (None, "", []):
                    parts.append(f"{k} 为 {v}")
            if parts:
                doc += "；".join(parts) + "。\n\n"

        # 帖级赞/藏：写入入库正文（档位或精确数由 kg_engagement_doc_mode 控制）
        lk, cl = post.get("liked_count"), post.get("collected_count")
        if lk is None and cl is None and isinstance(rd, dict):
            lk, cl = rd.get("liked_count"), rd.get("collected_count")
        sent = engagement_sentence_for_kg_doc(lk, cl)
        if sent:
            doc += sent

        return doc

    def _crawler_post_to_document(self, post: Dict) -> str:
        """爬虫原始帖子（顶层 title/desc/tags…）。"""
        title = post.get('title', '')
        desc = post.get('desc', '')
        tags = post.get('tags', [])
        if not isinstance(tags, list):
            tags = []
        search_keyword = post.get('search_keyword', '')
        liked_count = post.get('liked_count', 0)
        collected_count = post.get('collected_count', 0)

        doc = self._merchandising_kg_intro()
        if tags:
            doc += f"\n帖子标签作{', '.join(tags)}。\n"
        if desc:
            doc += f"\n{desc}\n"
        if title:
            doc += f"\n标题作「{title}」，可按词拆出衣著相关概念。\n"

        ct = (post.get("crawl_time") or "").strip()
        tl = self._post_info_time_lines(ct)
        if tl:
            doc += "\n" + tl.replace("- ", "").replace("\n", " ")

        if "image_analysis" in post:
            doc += self._format_image_analysis(post["image_analysis"])

        if search_keyword or liked_count or collected_count:
            doc += "\n"
            if search_keyword:
                doc += f"检索词串含{search_keyword}。"
            sent = engagement_sentence_for_kg_doc(liked_count, collected_count)
            if sent:
                doc += sent
        return doc

    def _post_to_document(self, post: Dict) -> str:
        """
        将单条记录转为结构化文档文本。
        支持：1) tag_annotation 穿搭级输出；2) 爬虫帖子级 JSON。
        """
        if self._is_annotated_outfit_record(post):
            return self._annotated_outfit_to_document(post)
        return self._crawler_post_to_document(post)

    def _format_image_analysis(self, analysis: Dict) -> str:
        """
        格式化图像分析结果为文本

        Args:
            analysis: 图像分析结果

        Returns:
            格式化的文本
        """
        doc = "\n单品与属性如下。\n"

        if analysis.get("categories"):
            doc += f"出现的服装品类包括{', '.join(analysis['categories'])}。\n"

        if analysis.get("items"):
            for item in analysis["items"]:
                cat = item.get("category", "单品")
                segs = [f"「{cat}」"]
                if item.get("style"):
                    segs.append(item["style"])
                if item.get("colors"):
                    segs.append("颜色含" + "、".join(item["colors"]))
                if item.get("material"):
                    segs.append(item["material"])
                if item.get("details"):
                    d = item["details"]
                    for key, label in (
                        ("neckline", "领"),
                        ("sleeve", "袖"),
                        ("length", "长"),
                        ("fit", "版型"),
                    ):
                        if d.get(key) and str(d[key]).strip() not in ("不适用", "N/A"):
                            segs.append(f"{label}{d[key]}")
                doc += "，".join(segs) + "。\n"

        if analysis.get("color_scheme"):
            color = analysis["color_scheme"]
            segs = []
            if color.get("primary"):
                segs.append(f"主色偏{color['primary']}")
            if color.get("secondary"):
                segs.append("辅色含" + "、".join(color["secondary"]))
            if color.get("combination"):
                segs.append(f"观感{color['combination']}")
            if segs:
                doc += "配色上，" + "；".join(segs) + "。\n"

        if analysis.get("overall_style"):
            doc += f"整体风格偏{', '.join(analysis['overall_style'])}。\n"

        if analysis.get("outfit_combination"):
            doc += f"{analysis['outfit_combination']}\n"

        if analysis.get("occasions"):
            doc += f"常见穿着场景含{', '.join(analysis['occasions'])}。\n"

        if analysis.get("seasons"):
            doc += f"适用季节含{', '.join(analysis['seasons'])}。\n"

        if analysis.get("body_types"):
            doc += f"身材方面包括{', '.join(analysis['body_types'])}。\n"

        return doc

    async def query(
        self,
        question: str,
        mode: str = "hybrid",
        top_k: int = 20
    ) -> Dict:
        """
        查询知识图谱

        Args:
            question: 查询问题
            mode: 查询模式 (local/global/hybrid/naive/mix)
            top_k: 返回结果数量

        Returns:
            查询结果
        """
        if not self.rag:
            await self.initialize()

        print(f"\n查询: {question}")
        print(f"模式: {mode}")

        try:
            result = await self.rag.aquery(
                question,
                param=QueryParam(
                    mode=mode,
                    top_k=top_k,
                    max_total_tokens=30000
                )
            )

            return {
                'question': question,
                'answer': result,
                'mode': mode,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            print(f"查询失败: {e}")
            return {
                'question': question,
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    async def query_data(
        self,
        question: str,
        mode: str = "hybrid",
        top_k: int = 20,
    ) -> Dict[str, Any]:
        """
        仅做检索结构化结果（实体/关系/chunk 与 file_path），不调用生成模型。
        供选品等场景从 ``file_path`` 回溯原始 JSON。
        """
        if not self.rag:
            await self.initialize()
        return await self.rag.aquery_data(
            question,
            param=QueryParam(
                mode=mode,
                top_k=top_k,
                max_total_tokens=30000,
            ),
        )

    def build_selection_question(self, criteria: Dict) -> str:
        """
        构建与 ``query_for_selection`` 相同的主问题文本（便于与 ``query_data`` 共用）。
        """
        question_parts: List[str] = []

        if criteria.get("season"):
            question_parts.append(f"{criteria['season']}季节")

        temp = criteria.get("temperature") or criteria.get("temperature_range")
        if temp:
            t = str(temp).strip()
            if t.endswith("度") or "度" in t:
                question_parts.append(f"{t}天气")
            else:
                question_parts.append(f"{t}度天气")

        style = criteria.get("style") or criteria.get("target_style")
        if style:
            question_parts.append(f"{style}风格")

        occasion = criteria.get("occasion")
        if occasion:
            question_parts.append(f"{occasion}场景")

        if not question_parts:
            question_parts.append("服装")

        return (
            f"推荐适合{'、'.join(question_parts)}的服装品类和搭配方案，包括具体的服装类型、"
            "颜色搭配、材质选择，以及为什么这些选择受欢迎。"
        )

    async def query_for_selection(self, criteria: Dict) -> Dict:
        """
        为选品决策查询知识图谱

        Args:
            criteria: 选品条件
                - season: 季节 (春/夏/秋/冬)
                - style: 风格 (甜美/休闲/韩系等)
                - temperature: 温度范围
                - occasion: 场景 (通勤/约会等)

        Returns:
            选品建议
        """
        question = self.build_selection_question(criteria)
        result = await self.query(question, mode="hybrid", top_k=30)
        return result

    async def get_trending_categories(self) -> Dict:
        """获取热门品类"""
        question = "根据点赞数和收藏数，列出当前最热门的服装品类，并说明每个品类的特点和流行原因。"
        return await self.query(question, mode="global")

    async def get_style_recommendations(self, style: str) -> Dict:
        """获取特定风格的搭配建议"""
        question = f"详细介绍{style}风格的服装搭配方案，包括推荐的品类、颜色、材质和具体搭配建议。"
        return await self.query(question, mode="local")

    async def get_seasonal_trends(self, season: str) -> Dict:
        """获取季节性趋势"""
        question = f"分析{season}季节的服装流行趋势，包括热门品类、流行颜色、常见搭配和用户偏好。"
        return await self.query(question, mode="hybrid")

    async def analyze_temperature_range(self, temp_range: str) -> Dict:
        """分析温度范围的穿搭建议"""
        question = f"针对{temp_range}的温度，推荐合适的服装品类、材质选择和搭配方案。"
        return await self.query(question, mode="hybrid")

    async def finalize(self):
        """清理资源"""
        if self.rag:
            await self.rag.finalize_storages()
            print("知识图谱已关闭")


async def build_kg_from_json(json_file: str, working_dir: str = "kg_storage"):
    """
    从 JSON 文件构建知识图谱

    Args:
        json_file: 小红书数据 JSON 文件路径
        working_dir: 知识图谱存储目录
    """
    print("=" * 60, flush=True)
    print("服装知识图谱构建", flush=True)
    print("=" * 60, flush=True)

    # 加载数据（超大 JSON 仅解析就可能数分钟，期间务必有提示）
    print(f"\n加载数据: {json_file}", flush=True)
    file_size_mb = os.path.getsize(json_file) / (1024 * 1024)
    print(
        f"文件约 {file_size_mb:.1f} MB，正在解析 JSON（大文件请耐心等待，非卡死）…",
        flush=True,
    )
    with open(json_file, 'r', encoding='utf-8') as f:
        posts = json.load(f)

    print(f"共加载 {len(posts)} 条记录（爬虫帖子或标注穿搭级）", flush=True)

    # 创建知识图谱
    kg = ClothingKnowledgeGraph(working_dir=working_dir)

    try:
        # 构建图谱
        await kg.build_from_posts(posts, batch_size=10, source_json=json_file)

        # 测试查询
        print("\n" + "=" * 60)
        print("测试查询")
        print("=" * 60)

        # 1. 热门品类
        print("\n1. 查询热门品类...")
        result = await kg.get_trending_categories()
        print(f"结果: {result['answer'][:200]}...")

        # 2. 风格推荐
        print("\n2. 查询甜美风格搭配...")
        result = await kg.get_style_recommendations("甜美")
        print(f"结果: {result['answer'][:200]}...")

        # 3. 季节趋势
        print("\n3. 查询春季趋势...")
        result = await kg.get_seasonal_trends("春季")
        print(f"结果: {result['answer'][:200]}...")

        print("\n" + "=" * 60)
        print("知识图谱构建和测试完成！")
        print("=" * 60)

    finally:
        await kg.finalize()


if __name__ == "__main__":
    import sys

    # 避免长时间无输出：尽量行缓冲（终端支持时）
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass

    if len(sys.argv) < 2:
        print("用法: python kg_builder.py <json_file> [working_dir]")
        print("      python kg_builder.py --list-entities [working_dir]")
        print("      python kg_builder.py --delete-entities <working_dir> <names.txt>")
        print("      python kg_builder.py --delete-relations <working_dir> <pairs.txt>")
        print("示例: python kg_builder.py clothing_data/clothing_posts_20260414.json")
        print("      python kg_builder.py crawlers/clothing_data/xxx_annotated.json")
        print("      python kg_builder.py --list-entities kg_storage   # 仅导出实体目录，不重跑构建")
        print("      python kg_builder.py --delete-entities kg_storage to_delete.txt")
        print("      # pairs.txt 每行: 实体A<TAB>实体B（仅删这条边，不删节点）")
        sys.exit(1)

    if sys.argv[1] == "--list-entities":
        working_dir = sys.argv[2] if len(sys.argv) > 2 else "kg_storage"

        async def _export_only():
            kg = ClothingKnowledgeGraph(working_dir=working_dir)
            try:
                await kg.export_entities_catalog()
            finally:
                await kg.finalize()

        asyncio.run(_export_only())
        sys.exit(0)

    if sys.argv[1] == "--delete-entities":
        if len(sys.argv) < 4:
            print("用法: python kg_builder.py --delete-entities <working_dir> <names.txt>")
            print("  names.txt: 每行一个实体名，与 entities_catalog.json 中 name 一致；# 开头为注释")
            sys.exit(1)
        working_dir, list_path = sys.argv[2], sys.argv[3]

        async def _delete_entities_cli():
            names = ClothingKnowledgeGraph._read_entity_names_file(list_path)
            if not names:
                print("列表为空，未执行删除。", flush=True)
                return
            kg = ClothingKnowledgeGraph(working_dir=working_dir)
            try:
                print(f"将删除 {len(names)} 个实体…", flush=True)
                await kg.delete_entities_by_names(names)
            finally:
                await kg.finalize()

        asyncio.run(_delete_entities_cli())
        sys.exit(0)

    if sys.argv[1] == "--delete-relations":
        if len(sys.argv) < 4:
            print("用法: python kg_builder.py --delete-relations <working_dir> <pairs.txt>")
            print("  pairs.txt: 每行 实体A<TAB>实体B（制表符分隔）")
            sys.exit(1)
        working_dir, list_path = sys.argv[2], sys.argv[3]

        async def _delete_relations_cli():
            pairs = ClothingKnowledgeGraph._read_relation_pairs_file(list_path)
            if not pairs:
                print("列表为空，未执行删除。", flush=True)
                return
            kg = ClothingKnowledgeGraph(working_dir=working_dir)
            try:
                print(f"将删除 {len(pairs)} 条边…", flush=True)
                await kg.delete_relations_by_pairs(pairs)
            finally:
                await kg.finalize()

        asyncio.run(_delete_relations_cli())
        sys.exit(0)

    json_file = sys.argv[1]
    working_dir = sys.argv[2] if len(sys.argv) > 2 else "kg_storage"

    print(
        "提示: 若开头长时间无输出，多为在加载 LightRAG 等依赖；"
        "超大 JSON 解析与文档转换也会较久。也可用: python -u kg_builder.py ...\n",
        flush=True,
    )

    asyncio.run(build_kg_from_json(json_file, working_dir))
