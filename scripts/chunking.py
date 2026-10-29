"""Section-aware chunking of T&C documents.

Each chunk carries the heading path it lives under (``section``). The section is
NOT part of ``content`` (which is shown to the user and used to build the
``#:~:text=`` source link): it is prepended only to the text that gets embedded
and indexed, so "You can delete it within 30 days" is known to be about
"Content Removal and Disabling or Terminating Your Account".
"""
import re
from dataclasses import dataclass

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

# multilingual-e5-small reads 512 tokens (~2000 chars), so 1000-char chunks are embedded
# in full. (The previous model, paraphrase-multilingual-MiniLM, read only 128 tokens and
# silently truncated them.) Measured with scripts/eval: 1000 + sections was the best size.
DEFAULT_SIZE = 1000
DEFAULT_OVERLAP = 160

_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4"), ("#####", "h5"), ("######", "h6")]
# Some pages come back as one single line: "... text ## **5. Rights** text ..."
_INLINE_HEADING = re.compile(r"(?<=\S)[ \t]+(?=#{2,6} [*\w])")
# A line that is only bold text is a heading in legal docs: "**4.3 Permissions You Give to Us.**"
_BOLD_LINE = re.compile(r"^\*\*([^*\n]{3,90}?)\.?\*\*:?$", re.MULTILINE)
_MAX_SECTION_CHARS = 120


@dataclass
class Chunk:
    content: str
    section: str = ""

    @property
    def embed_text(self) -> str:
        """Text to embed and index: the section gives the chunk its topic."""
        return f"{self.section}\n{self.content}" if self.section else self.content


def _normalise(text: str) -> str:
    text = _INLINE_HEADING.sub("\n\n", text)
    return _BOLD_LINE.sub(r"###### \1", text)


def chunk_document(text: str, size: int = DEFAULT_SIZE, overlap: int = DEFAULT_OVERLAP) -> list[Chunk]:
    """Split *text* into overlapping chunks that remember their heading path."""
    sections = MarkdownHeaderTextSplitter(_HEADERS, strip_headers=False).split_text(_normalise(text))
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    chunks = []
    for doc in sections:
        path = [doc.metadata[k] for _, k in _HEADERS if k in doc.metadata]
        section = " > ".join(p.strip(" *#") for p in path)[:_MAX_SECTION_CHARS]
        for piece in splitter.split_text(doc.page_content):
            piece = piece.strip()
            if piece:
                chunks.append(Chunk(piece, section))
    return chunks
