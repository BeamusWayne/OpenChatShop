"""Unit tests for safe WeChat outbound XML construction (audit MEDIUM).

Why this matters: the outbound reply was built by string-concatenating
``<![CDATA[...]]>`` blocks. When user/business content contains the ``]]>``
terminator or raw XML metacharacters (``<``, ``&``), naive concatenation
breaks the XML structure and opens an injection vector. These tests pin the
invariant: whatever the content, the produced envelope must be well-formed XML
that round-trips the exact content back through a real XML parser.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from open_chat_shop.api.wechat import _build_reply_xml


def _field_text(root: ET.Element, name: str) -> str | None:
    """Return the text of a child element, or None if absent."""
    el = root.find(name)
    return el.text if el is not None else None


def _parsed_fields(xml_text: str) -> dict[str, str | None]:
    """Parse an outbound reply and return its field texts.

    Raises ``ET.ParseError`` (failing the test) if the envelope is malformed.
    """
    root = ET.fromstring(xml_text)
    names = ("ToUserName", "FromUserName", "MsgType", "Content")
    return {name: _field_text(root, name) for name in names}


class TestBuildReplyXmlIsWellFormed:
    """The envelope must always parse and carry the protocol fields."""

    def test_plain_content_roundtrips(self) -> None:
        xml_text = _build_reply_xml(
            to_user="user_123", from_user="gh_abc", content="你好，欢迎光临。"
        )
        fields = _parsed_fields(xml_text)
        assert fields["ToUserName"] == "user_123"
        assert fields["FromUserName"] == "gh_abc"
        assert fields["MsgType"] == "text"
        assert fields["Content"] == "你好，欢迎光临。"

    def test_create_time_is_present_and_integer(self) -> None:
        xml_text = _build_reply_xml(
            to_user="u", from_user="gh", content="hello"
        )
        root = ET.fromstring(xml_text)
        create_time = root.find("CreateTime")
        assert create_time is not None and create_time.text is not None
        # WeChat requires CreateTime to be an integer epoch seconds value.
        assert create_time.text.isdigit()


class TestContentWithCdataTerminator:
    """A ``]]>`` sequence in content must not break the envelope."""

    def test_cdata_terminator_in_content_is_safe(self) -> None:
        # If naively wrapped as <![CDATA[ ... ]]> ... ]]>, the first ]]>
        # would prematurely close the section and corrupt the XML.
        evil = "price is 5 if x>0 ]]> and then <script>alert(1)</script>"
        xml_text = _build_reply_xml(
            to_user="user_123", from_user="gh_abc", content=evil
        )
        # Must parse as well-formed XML.
        fields = _parsed_fields(xml_text)
        # And the content must round-trip byte-for-byte.
        assert fields["Content"] == evil

    def test_double_cdata_terminator(self) -> None:
        evil = "]]>]]>"
        xml_text = _build_reply_xml(
            to_user="u", from_user="gh", content=evil
        )
        assert _parsed_fields(xml_text)["Content"] == evil


class TestContentWithXmlMetacharacters:
    """Raw ``<``, ``&``, ``>`` and quotes must be carried safely."""

    @pytest.mark.parametrize(
        "content",
        [
            "<b>bold</b>",
            "a & b",
            "1 < 2 and 3 > 2",
            'he said "hi" & \'bye\'',
            "</Content><MsgType>injected</MsgType>",
            "混合 & <tag> ]]> 内容",
        ],
    )
    def test_metacharacters_roundtrip(self, content: str) -> None:
        xml_text = _build_reply_xml(
            to_user="user_123", from_user="gh_abc", content=content
        )
        fields = _parsed_fields(xml_text)
        # Parses cleanly AND the content is preserved exactly — i.e. an
        # attempted injected </Content><MsgType> stays inert text, not markup.
        assert fields["Content"] == content
        assert fields["MsgType"] == "text"
        assert fields["ToUserName"] == "user_123"

    def test_injection_does_not_create_extra_elements(self) -> None:
        # A classic injection attempt: try to smuggle a second MsgType.
        content = "</Content></xml><xml><MsgType><![CDATA[news]]></MsgType>"
        xml_text = _build_reply_xml(
            to_user="u", from_user="gh", content=content
        )
        root = ET.fromstring(xml_text)
        # Exactly one MsgType, and it is still the real "text" one.
        assert len(root.findall("MsgType")) == 1
        assert root.find("MsgType").text == "text"
        assert root.find("Content").text == content
