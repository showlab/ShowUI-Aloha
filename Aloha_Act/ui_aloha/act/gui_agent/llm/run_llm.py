import os
from openai import OpenAI
from ui_aloha.act.gui_agent.llm.llm_utils import gbk_encode_decode, is_image_path, encode_image



def _prepare_messages(messages: list, system: str) -> list:
    
    final_messages = [
        {"role": "system", "content": [{"type": "text", "text": system}]}
    ]

    if isinstance(messages, str):
        final_messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": gbk_encode_decode(messages)
                }]
            })
        return final_messages

    for item in messages:
        contents = []
        if isinstance(item, dict) and "content" in item:
            for cnt in item["content"]:
                if isinstance(cnt, str):
                    if is_image_path(cnt):
                        base64_image = encode_image(cnt)
                        content = {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                            }
                    else:
                        content = {
                            "type": "text",
                            "text": gbk_encode_decode(cnt)
                            }
                    
                    contents.append(content)
        
            final_messages.append({"role": "user", "content": contents})
        
        elif isinstance(item, str):
            contents.append({"type": "text", "text": gbk_encode_decode(item)})
            final_messages.append({"role": "user", "content": contents})

    return final_messages


def _to_responses_input(final_messages: list) -> list:
    responses_input = []
    for msg in final_messages:
        role = msg.get("role", "user")
        contents = []
        for item in msg.get("content", []):
            if item.get("type") == "text":
                contents.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                image_url = (item.get("image_url") or {}).get("url")
                if image_url:
                    contents.append({"type": "input_image", "image_url": image_url})
        # Responses API expects a dict with role and content list
        responses_input.append({"role": role, "content": contents})
    return responses_input


def _process_responses_output(response):
    
    model = getattr(response, "model", None)
    outputs = getattr(response, "output", None)
    
    if outputs and len(outputs) > 0:
        
        # skip thinking output
        for output in outputs:
            if hasattr(output, "type") and output.type in ["thinking", "reasoning"]:
                continue
            
            # get the first content
            content = output.content
        
        if content and len(content) > 0 and hasattr(content[0], "text"):
            text = content[0].text
    
    else:
        text = ""
        
    usage = getattr(response, "usage", None)
    total_tokens = 0
    if usage is not None:
        total_tokens = getattr(usage, "total_tokens", None)
        if total_tokens is None:
            total_tokens = int(getattr(usage, "input_tokens", 0) + getattr(usage, "output_tokens", 0))
    return text, model, total_tokens



def run_llm(
    messages: list,
    system: str,
    llm: str,
    max_tokens: int = 2048,
    temperature: float = 0,
    api_keys: dict | None = None,
    mode: str = "api",  # kept for compatibility; not used
    api_base: str | None = None,  # None for OpenAI API base
):
    """
    Basic LLM caller using OpenAI-compatible Chat Completions HTTP API.
    
    Returns:
        (response_text, token_usage_dict) where token_usage_dict is {"model_name": token_count}
    """

    api_key = None
    if api_keys and "OPENAI_API_KEY" in api_keys:
        api_key = api_keys["OPENAI_API_KEY"]
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Error: api_keys with OPENAI_API_KEY is required.", {llm: 0}

    client_kwargs = {}
    if api_base:
        client_kwargs["base_url"] = api_base
    if api_key:
        client_kwargs["api_key"] = api_key
        
    # Create client
    client = OpenAI(**client_kwargs)

    final_messages = _prepare_messages(messages, system)
    responses_input = _to_responses_input(final_messages)
    
    # special handling for gpt-5
    if llm.startswith("gpt-5"):
        llm_kwargs = {
            "reasoning": { "effort": "minimal" },
            "text": { "verbosity": "medium" },
        }   
    else:
        llm_kwargs = {}
    
    response = client.responses.create(
        model=llm,
        input=responses_input,
        max_output_tokens=max_tokens,
        temperature=temperature if not llm.startswith("gpt-5") else None,
        **llm_kwargs
    )

    text, model, total_tokens = _process_responses_output(response)
    token_usage_dict = {model: total_tokens}
    return text, token_usage_dict

