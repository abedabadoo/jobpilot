from jobpilot import keywords


def test_extracts_required_tools_and_disciplines_with_aliases_and_no_noise():
    job = {
        "title": "Cloud Security Engineer",
        "description": """<h2>Requirements</h2><p>Use Amazon Web Services, Terraform,
        Kubernetes and Wiz for cloud security, IAM, vulnerability management and SOC2
        evidence. We offer competitive pay, unlimited vacation and a great team.</p>""",
    }
    result = keywords.extract_keywords(job)
    assert {"AWS", "Terraform", "Kubernetes", "Wiz"} <= set(result["tools"])
    assert {"Cloud security", "IAM", "Vulnerability management", "SOC 2"} <= set(result["skills"])
    assert not {"competitive pay", "great team", "Requirements", "vacation"} & set(result["terms"])
    assert len(result["terms"]) == len(set(result["terms"]))


def test_profile_match_does_not_filter_out_additional_job_tools():
    profile = {
        "skills": ["AWS", "Python"],
        "experience": [{"facts": [{"text": "Reviewed IAM policies."}]}],
    }
    result = keywords.extract_keywords(
        {"description": "AWS IAM Python Terraform SentinelOne"}, profile
    )
    assert {"AWS", "IAM", "Python"} <= set(result["matched"])
    assert {"Terraform", "SentinelOne"} <= set(result["suggested"])
    assert set(result["matched"]) | set(result["suggested"]) == set(result["terms"])
    assert not set(result["matched"]) & set(result["suggested"])


def test_extracts_meaningful_keywords_for_non_security_roles():
    result = keywords.extract_keywords(
        {
            "title": "Marketing Operations Analyst",
            "description": "Required experience with Salesforce, HubSpot and Tableau. Own marketing automation, lead generation, campaign management and data analysis.",
        }
    )
    assert {"Salesforce", "HubSpot", "Tableau"} <= set(result["tools"])
    assert {
        "Marketing automation",
        "Lead generation",
        "Campaign management",
        "Data analysis",
    } <= set(result["skills"])


def test_required_context_can_capture_new_named_tools_without_claiming_credentials():
    result = keywords.extract_keywords(
        {
            "description": "Experience with ZephyrScan and AcmeDefender is required. CISSP and a master's degree preferred.",
        }
    )
    assert {"ZephyrScan", "AcmeDefender"} <= set(result["tools"])
    assert "CISSP" not in result["terms"]
    assert not any("degree" in term.lower() for term in result["terms"])


def test_empty_or_missing_description_has_a_stable_result_shape():
    result = keywords.extract_keywords({})
    assert result == {"terms": [], "tools": [], "skills": [], "matched": [], "suggested": []}


def test_recruiting_footer_is_not_treated_as_a_security_skill():
    result = keywords.extract_keywords(
        {
            "title": "Security Engineer",
            "description": "Use AWS and IAM.\n**Reasonable Accommodation**\nContact your recruiter about the recruiting process.\n**Equal Employment Opportunity Statement**\nRead our Recruiting and Hiring Statement.",
        }
    )
    assert "Recruiting" not in result["terms"]
    assert {"AWS", "IAM"} <= set(result["terms"])


def test_agentic_ai_roles_include_frameworks_protocols_and_delivery_work():
    result = keywords.extract_keywords(
        {
            "title": "AI Forward Deployed Engineer",
            "description": "Build agentic AI using LangGraph, LangChain, Azure OpenAI and MCP. Apply retrieval-augmented generation, prompt engineering and model evaluation to client delivery.",
        }
    )
    assert {"LangGraph", "LangChain", "Azure OpenAI"} <= set(result["tools"])
    assert {
        "Agentic AI",
        "MCP",
        "RAG",
        "Prompt engineering",
        "Model evaluation",
        "Client delivery",
    } <= set(result["skills"])
