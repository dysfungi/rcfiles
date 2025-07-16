"""
References:
    https://xon.sh/tutorial.html#customizing-the-prompt
"""
from _utils import rc


@rc(interactive=True)
def __rc_interactive_prompt(xsh):
    from prompt_toolkit.key_binding.vi_state import InputMode as ViInputMode
    from xonsh.prompt import gitstatus, vc
    from xonsh.prompt.base import PromptField, PromptFields

    def _vi_input_mode():
        # https://github.com/t184256/xontrib-prompt-vi-mode
        style = "{BLUE}"
        text = "UNKNOWN"

        # TODO: handle case VISUAL, which is not in ViInputMode
        match xsh.shell.shell.prompter.app.vi_state.input_mode:
            case ViInputMode.INSERT:
                text = "INSERT"
            case ViInputMode.INSERT_MULTIPLE:
                text = "INSERT_MULTIPLE"
            case ViInputMode.NAVIGATION:
                style = "{BLACK}"
                text = "NORMAL"
            case ViInputMode.REPLACE:
                text = "REPLACE"
            case (_ as mode):
                style = "{INTENSE_RED}"
                text = mode.name

        return f"{style} {text} {{RESET}}"

    def _bottom_toolbar():
        $PROMPT_FIELDS["threaded_result"] = " ".join($PROMPT_FIELDS.setdefault("threaded_results", []))
        return f"{_vi_input_mode()}{{threaded_result:{{RED}}{{}}{{RESET}}}}"

    # https://xon.sh/envvars.html#interactive-prompt
    # https://github.com/xonsh/xonsh/issues/5301#issuecomment-1995160635
    $UPDATE_PROMPT_ON_KEYPRESS = True
    $BOTTOM_TOOLBAR = _bottom_toolbar
    # $MULTILINE_PROMPT = "`·.,¸,.·*¯`·.,¸,.·*¯"
    $MULTILINE_PROMPT = "{GREEN}╰──────────────{INTENSE_GREEN}··{RESET}"
    $PROMPT = "\n".join([
        "{GREEN}┬─[{INTENSE_WHITE}{short_cwd}{GREEN}]─[{branch_color}{gitstatus.branch}{BOLD_INTENSE_BLUE}{gitstatus.ahead}{BOLD_RED}{gitstatus.behind}{GREEN}]─({YELLOW}{env_name}{GREEN})",
        "{GREEN}╰─[{PURPLE}{localtime}{GREEN}]─{prompt_end} ",
    ])
    $RIGHT_PROMPT = "{last_return_code_if_nonzero:{RED}[{BOLD_INTENSE_RED}{}{RED}]}{RESET}"
    $TITLE = "{current_job:{} | }{user}"

    $PROMPT_FIELDS["env_prefix"] = $PROMPT_FIELDS["env_postfix"] = ""
    # https://xon.sh/api/_autosummary/cmd/xonsh.prompt.gitstatus.html
    gitstatus_branch = $PROMPT_FIELDS["gitstatus.branch"]
    gitstatus_branch.prefix = ""
    gitstatus_branch.suffix = "{RESET}"
    $PROMPT_FIELDS["prompt_end"] = "{INTENSE_GREEN}@>{RESET}"
    $PROMPT_FIELDS["time_format"] = "%s"
    $PROMPT_FIELDS["vi_input_mode"] = _vi_input_mode  # TODO: fix
