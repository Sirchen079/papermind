"""Validated human questions and answers shared by the harness and chat API."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
SKIP_TEXT = "跳过这些问题，请根据已有信息继续，并说明必要的假设。"


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: ShortText
    options: list[ShortText] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def unique_options(self):
        if len(set(self.options)) != len(self.options):
            raise ValueError("建议答案不能重复")
        return self


class AskUser(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[Question] = Field(min_length=1, max_length=3)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=600)] = ""


class ClarificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: int = Field(gt=0)
    answers: dict[str, AnswerText] = Field(default_factory=dict, max_length=3)
    free_text: AnswerText | None = None
    skipped: bool = False

    @model_validator(mode="after")
    def one_answer_mode(self):
        if sum((bool(self.answers), self.free_text is not None, self.skipped)) != 1:
            raise ValueError("请选择填写答案、自由补充或跳过其中一种方式")
        return self


def question_request(arguments: dict) -> dict:
    request = AskUser.model_validate(arguments)
    return {
        "reason": request.reason,
        "questions": [{"id": f"q{i + 1}", **q.model_dump()} for i, q in enumerate(request.questions)],
        "status": "pending",
    }


def question_content(request: dict) -> str:
    lines = [request["reason"]] if request.get("reason") else []
    for q in request["questions"]:
        lines.append(q["question"])
        if q["options"]:
            lines.append("建议答案：" + " / ".join(q["options"]))
    return "\n\n".join(lines)


def answer_content(request: dict, response: ClarificationResponse) -> str:
    if response.skipped:
        return SKIP_TEXT
    if response.free_text is not None:
        return response.free_text
    expected = {q["id"] for q in request["questions"]}
    if set(response.answers) != expected:
        raise ValueError("请回答全部问题，或选择自由补充或跳过")
    return "补充信息：\n" + "\n\n".join(
        q["question"] + "\n" + response.answers[q["id"]] for q in request["questions"]
    )
