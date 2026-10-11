"""Shared extraction schemas for service and evaluation."""

EVENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["events"],
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id","subject","actor","requester","related_people","action","recipient","event_type","status","time_scope","deadline","prerequisite","constraint","note","certainty","evidence"],
                "properties": {
                    "source_id": {"type": "string"},
                    "subject": {"type": ["string","null"]},
                    "actor": {"type": ["object","null"], "additionalProperties": False, "properties": {"slack_id":{"type":["string","null"]},"name":{"type":"string"}}, "required":["slack_id","name"]},
                    "related_people": {"type":"array","items":{"type":"object","additionalProperties":False,"required":["slack_id","name","role","certainty"],"properties":{"slack_id":{"type":["string","null"]},"name":{"type":"string"},"role":{"type":["string","null"]},"certainty":{"type":"string","enum":["confirmed","uncertain"]}}}},
                    "action": {"type": ["string","null"]},
                    "recipient": {"type": ["object","null"], "additionalProperties": False, "properties": {"slack_id":{"type":["string","null"]},"name":{"type":"string"}}, "required":["slack_id","name"]},
                    "requester": {"type": ["object","null"], "additionalProperties": False, "properties": {"slack_id":{"type":["string","null"]},"name":{"type":"string"}}, "required":["slack_id","name"]},
                    "event_type": {"type":"string","enum":["request","requirement","plan","progress","completion","status","question","decision"]},
                    "status": {"type":["string","null"]},
                    "time_scope": {"type":"string","enum":["past","current","future","unknown"]},
                    "deadline": {"type":"object","additionalProperties":False,"required":["text","at"],"properties":{"text":{"type":["string","null"]},"at":{"type":["string","null"]}}},
                    "prerequisite": {"type":["string","null"]},
                    "constraint": {"type":["string","null"]},
                    "note": {"type":["string","null"]},
                    "certainty": {"type":"string","enum":["confirmed","uncertain"]},
                    "evidence": {"type":"string"}
                }
            }
        }
    }
}

TASK_SCHEMA = {
    "type":"object","additionalProperties":False,"required":["tasks"],
    "properties":{"tasks":{"type":"array","items":{
        "type":"object","additionalProperties":False,
        "required":["task_id","title","subject","status","status_history","deadline","next_action","participants","events","task_links","certainty"],
        "properties":{
            "task_id":{"type":["string","null"]},"title":{"type":"string"},"subject":{"type":["string","null"]},
            "status":{"type":"string","enum":["planned","in_progress","waiting","blocked","completed","unknown"]},
            "status_history":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["from","to","changed_at"],"properties":{"from":{"type":["string","null"]},"to":{"type":["string","null"]},"changed_at":{"type":["string","null"]}}}},
            "deadline":{"type":"object","additionalProperties":False,"required":["text","at"],"properties":{"text":{"type":["string","null"]},"at":{"type":["string","null"]}}},
            "next_action":{"type":["string","null"]},
            "participants":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["slack_id","name","roles","event_ids"],"properties":{"slack_id":{"type":["string","null"]},"name":{"type":"string"},"roles":{"type":"array","items":{"type":"string"}},"event_ids":{"type":"array","items":{"type":"string"}}}}},
            "events":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["event_id","role"],"properties":{"event_id":{"type":"string"},"role":{"type":"string"}}}},
            "task_links":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["task_id","relation"],"properties":{"task_id":{"type":["string","null"]},"relation":{"type":["string","null"]}}}},
            "certainty":{"type":"string","enum":["confirmed","uncertain"]}
        }
    }}}
}

WORK_SCHEMA = {
    "type":"object","additionalProperties":False,"required":["works"],
    "properties":{"works":{"type":"array","items":{
        "type":"object","additionalProperties":False,
        "required":["work_id","title","tasks","certainty"],
        "properties":{
            "work_id":{"type":["string","null"]},"title":{"type":"string"},
            "tasks":{"type":"array","items":{"type":"object","additionalProperties":False,"required":["task_id","role"],"properties":{"task_id":{"type":"string"},"role":{"type":"string"}}}},
            "certainty":{"type":"string","enum":["confirmed","uncertain"]}
        }
    }}}
}
