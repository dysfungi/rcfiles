from xonsh.built_ins import XSH


def reset_current_job():
    if not XSH.shell:
        return

    prompt_fields = XSH.env["PROMPT_FIELDS"]
    with prompt_fields["current_job"].update_current_cmds([["xonsh"]]):
        prompt_fields.reset_key("current_job")
        XSH.shell.settitle()
