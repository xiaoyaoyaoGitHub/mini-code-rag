from pathlib import Path
import re
from .config import Config
from .scan import iter_files

LANG_SPECS: dict[str, dict] = {
    "python": {
        "def_types": {"function_definition", "class_definition"},
        "call_types": {"call"},
        "import_types": {"import_statement", "import_from_statement"},
        "docstring_is_string": True,   # body 第一个 named child 是 string 就是 docstring
    },
    "javascript": {
        "def_types": {
            "function_declaration", "class_declaration",
            "method_definition", "function_expression",
        },
        "call_types": {"call_expression"},
        "import_types": {"import_statement"},
        "docstring_is_string": False,
    },
    "typescript": {
        "def_types": {
            "function_declaration", "class_declaration",
            "method_definition", "function_expression",
        },
        "call_types": {"call_expression"},
        "import_types": {"import_statement"},
        "docstring_is_string": False,
    },
    "tsx": {
        "def_types": {
            "function_declaration", "class_declaration",
            "method_definition", "function_expression",
        },
        "call_types": {"call_expression"},
        "import_types": {"import_statement"},
        "docstring_is_string": False,
    },
    "go": {
        "def_types": {"function_declaration", "method_declaration"},
        "call_types": {"call_expression"},
        "import_types": {"import_declaration"},
        "docstring_is_string": False,
    },
    "java": {
        "def_types": {
            "method_declaration", "class_declaration",
            "constructor_declaration",
        },
        "call_types": {"method_invocation"},
        "import_types": {"import_declaration"},
        "docstring_is_string": False,
    },
    "rust": {
        "def_types": {"function_item", "struct_item", "impl_item"},
        "call_types": {"call_expression", "macro_invocation"},
        "import_types": {"use_declaration"},
        "docstring_is_string": False,
    },
    "ruby": {
        "def_types": {"method", "class", "singleton_method"},
        "call_types": {"call"},
        "import_types": {"call"},  # ruby 的 require 是方法调用
        "docstring_is_string": False,
    },
}

def _spec(lang) -> dict:
    """取语言配置 不在表里的用通用规则兜底"""
    if lang in LANG_SPECS:
        return LANG_SPECS[lang]
    return {
        "def_types": set(),
        "call_types": set(),
        "import_types": set(),
        "docstring_is_string": False,
        "_generic": True,
    }

# 解析
def parse_file(path:Path, language:str):
    """ 使用 tree-sitter 解析文件 返回 root node """
    from  tree_sitter_language_pack import get_parser
    try:
        parser = get_parser(language)
    except Exception:
        return None

    source = path.read_bytes()
    tree = parser.parse(source)
    # print(f"tree.root_node,{tree.root_node}")
    # print(f"tree.root_node.type,{tree.root_node.type}")
    # print(f"tree.root_node.text,{tree.root_node.text}")
    # print(f"tree.root_node.start_point,{tree.root_node.start_point}")
    # print(f"tree.root_node.children,{tree.root_node.children}")
    # print(f"tree.root_node.named_children,{tree.root_node.named_children}")
    # print(f"tree.root_node.child_count,{tree.root_node.child_count}")
    if tree.root_node.has_error:
        pass
    return tree.root_node, source

# 判断是不是 import 节点
def _is_import_node(node, spec) -> bool:
    if node.type in spec["import_types"]:
        return True
    return False

def _walk(node):
    yield node
    for child in node.children:
        # yield from 让递归生成器摊平——所有层的 yield 都在同一个层级产出，调用方一次遍历拿全部：
        yield from _walk(child)

#  import
def extract_imports(root, spec) -> list[str]:
    """ 摘要 import 关键信息 """
    keywords = {"from", "import", "as", "use", "require", "include", "package", "static"}
    out:list[str] = []
    for node in _walk(root):
        if _is_import_node(node, spec):
            text = node.text.decode("utf-8", errors="replace")
            for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*",text):
                name = m.group()
                if name not in keywords:
                    out.append(name)
    return sorted(set(out))

def extract_calls(root, spec):
    for node in _walk(root):
        if _is_call_node(node, spec):
            # TODO
            pass


def _is_call_node(node ,spec):
    if node.type in spec["call_types"]:
        return True
    return False
# 判断是否为对应语言的def_types
def _is_def_node(node, spec):
    if node.type in spec["def_types"]:
        return True
    return False

# 获取节点名称
def _node_name(node):
    n = node.child_by_field_name("name")
    if n is not None:
        return n.text.decode('utf-8',errors="replace")
    # 找到第一个能识别的子节点
    for c in node.named_children:
        if c.type == 'identifier':
            return c.text.decode('utf-8',errors="replace")
    return "<anonymous>"

def walk_def_nodes(root, spec, units:list[str], chain:tuple = ()):
    for child in root.named_children:
        if _is_def_node(child, spec):
           yield child, chain
           yield from walk_def_nodes(child, spec, units, chain + (_node_name(child),))
        else:
            yield from walk_def_nodes(child, spec, units, chain)

# 获取节点的 body
def _node_body(node):
    return node.child_by_field_name("body") or node.child_by_field_name("block")

def _class_header_end(node):
    """ 要把 class 与方法单出拆开 避免变成一个巨大的 chunk """
    body = _node_body(node)
    if not body:
        return node.end_byte

    end = body.start_byte # 默认是 body的开头
    for child in node.named_children:
        if child.type in ("string", "assignment", "annotated_assignment", "field_declaration"):
            end = child.end_byte
            continue
        break
    return end

# 类型 简化版的判断 闭包方法会误判为 method 影响不大
def _kind(node, chain):
    if "class" in node.type:
        return "class"
    if chain:
        return "method"
    return "function"

def get_signature(node, source):
    """签名 = 节点开头到 body 开始之间的文本。
        对 Python 就是 `def foo(x) -> int:` 这一行；
        对 JS 就是 `function foo(x) {`；对 Go 就是 `func foo(x int) int {`。
        信息密度最高，喂给 embedding 比整个函数体更有效。
    """
    body = _node_body(node)
    if body:
        return source[node.start_byte:body.start_byte].decode("utf-8", errors="replace").strip()
    # 如果没有 body 直接取第一行
    first_line = source[node.start_byte:].split(b"\n",1)[0]
    return first_line.decode("utf-8", errors="replace").strip()

def get_docstring(spec):
    if spec['docstring_is_string']:
        # TODO python语法解析需要
        pass
    return ''


def make_chunk(node, spec, source, rel, chain, imports, project, cfg):
    """ 把 ast 节点变成一个 chunk dict """
    is_class = "class" in node.type
    name = _node_name(node)
    if is_class:
        end_byte = _class_header_end(node)
    else:
        end_byte = node.end_byte

    # 截取到对应的方法体
    code = source[node.start_byte:end_byte].decode('utf-8', errors="replace")
    start_line = source[:node.start_byte].count(b"\n") + 1
    end_line = source[:end_byte].count(b"\n") + 1

    sep = cfg.chunking.breadcrumb_sep
    breadcrumb = sep.join((rel, *chain, name))
    print(f"breadcrumb:{breadcrumb}")

    chunk = {
        "id":f"{project}:{rel}:{start_line}",
        "project":project,
        "file":rel,
        "start_line": start_line,
        "end_line": end_line,
        "language": cfg.ext_to_lang(Path(rel).suffix.lstrip('.')) or "unknow",
        "kind": _kind(node, chain),
        "name":name,
        "breadcrumb":breadcrumb,
        "signature": get_signature(node, source),
        "docstring":get_docstring(spec),
        "code":code,
        "imports":imports,
        "calls":extract_calls(node, spec)
    }
    return chunk

def chunk_file(path:Path, rel: str, language:str, name:str, cfg:Config):
    """ 切文件 """
    parsed = parse_file(path, language)
    if parsed is None:
        return []
    root, source = parsed
    spec = _spec(language)
    # 获取 import 相关的关键信息 去除语义值
    imports = extract_imports(root, spec)
    units = cfg.chunking.units
    # 对节点进行遍历
    result = []
    for node, chain in walk_def_nodes(root, spec, units):
        make_chunk(node, spec, source, rel, chain, imports, name, cfg)

    return result



def iter_chunks(cfg:Config):
    # 读取文件列表
    for file in iter_files(cfg):
        # print(f"file:{file.rel}, {file.language}")
        # 对文件内容进行切片转换
        chunk_file(file.path, file.rel, file.language, cfg.project.name, cfg)


