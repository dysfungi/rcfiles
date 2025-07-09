"""
Defaults:
    https://github.com/prompt-toolkit/python-prompt-toolkit/blob/main/src/prompt_toolkit/key_binding/bindings/vi.py#L403
    https://github.com/xonsh/xonsh/blob/main/xonsh/shells/ptk_shell/key_bindings.py#L216

References:
    https://xon.sh/envvars.html#vi-mode
    https://xon.sh/tutorial_ptk.html
    https://python-prompt-toolkit.readthedocs.io/en/master/pages/asking_for_input.html#vi-input-mode
    https://python-prompt-toolkit.readthedocs.io/en/master/pages/asking_for_input.html#adding-custom-key-bindings
    https://python-prompt-toolkit.readthedocs.io/en/master/pages/advanced_topics/key_bindings.html
    https://python-prompt-toolkit.readthedocs.io/en/master/pages/advanced_topics/key_bindings.html#creating-new-vi-text-objects-and-operators
"""
from _utils import rc


@rc(interactive=True)
def __rc_interactive():
    from prompt_toolkit.filters.app import (
        vi_digraph_mode,
        vi_insert_mode,
        vi_insert_multiple_mode,
        vi_mode,
        vi_navigation_mode,
        vi_recording_macro,
        vi_replace_mode,
        # vi_replace_single_mode,
        vi_selection_mode,
        vi_waiting_for_text_object_mode,
    )
    from prompt_toolkit.key_binding.bindings.vi import create_operator_decorator, create_text_object_decorator
    from prompt_toolkit.key_binding.key_bindings import KeyBindings
    from prompt_toolkit.key_binding.vi_state import InputMode as ViInputMode
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.shortcuts.prompt import PromptSession
    from xonsh.shells.ptk_shell.completer import PromptToolkitCompleter
    from xonsh.shells.ptk_shell.history import PromptToolkitHistory

    # https://xon.sh/envvars.html#vi-mode
    $VI_MODE = True

    # https://xon.sh/envvars.html#xonsh-copy-on-delete
    $XONSH_COPY_ON_DELETE = True

    # https://xon.sh/envvars.html#xonsh-use-system-clipboard
    $XONSH_USE_SYSTEM_CLIPBOARD = True

    # @events.on_pre_prompt
    def debug(**kwargs):
        print("on_pre_prompt:", kwargs)
        import pdb; pdb.set_trace()
        pass

    # @events.on_post_prompt
    def debug(**kwargs):
        print("on_post_prompt:", kwargs)
        import pdb; pdb.set_trace()
        pass

    @events.on_ptk_create
    def custom_keybindings(
        bindings: KeyBindings,
        completer: PromptToolkitCompleter,
        history: PromptToolkitHistory,
        prompter: PromptSession,
        **kwargs
    ):
        """
        References:
            https://xon.sh/tutorial_ptk.html#custom-keyload-function

        """

        # https://github.com/prompt-toolkit/python-prompt-toolkit/blob/8f31416/src/prompt_toolkit/key_binding/bindings/vi.py#L1090
        operator = create_operator_decorator(bindings)
        text_object = create_text_object_decorator(bindings)

        # https://python-prompt-toolkit.readthedocs.io/en/master/pages/reference.html#prompt_toolkit.key_binding.KeyBindings.add
        @bindings.add(",", "m", filter=vi_insert_mode)
        def _exit_insert_mode(event):
            # https://python-prompt-toolkit.readthedocs.io/en/master/pages/reference.html#prompt_toolkit.key_binding.vi_state.ViState
            event.cli.vi_state.input_mode = ViInputMode.NAVIGATION

        @bindings.add("l", filter=vi_navigation_mode)
        def _enter_insert_mode(event):
            event.cli.vi_state.input_mode = ViInputMode.INSERT

        @bindings.add("L", filter=vi_navigation_mode)
        def _enter_insert_mode_before_the_first_non_blank_in_the_line(event):
            buffer = event.current_buffer
            document = buffer.document
            buffer.cursor_position += document.get_start_of_line_position(
                after_whitespace=True,
            )
            _enter_insert_mode(event)


        @bindings.add("e", filter=vi_navigation_mode | vi_selection_mode)
        def _navigate_up(event):
            event.current_buffer.auto_up(
                count=event.arg,
                go_to_start_of_line_if_history_changes=True,
            )

        @bindings.add("n", filter=vi_navigation_mode | vi_selection_mode)
        def _navigate_down(event):
            event.current_buffer.auto_down(
                count=event.arg,
                go_to_start_of_line_if_history_changes=True,
            )

        @bindings.add("h", filter=vi_navigation_mode | vi_selection_mode)
        def _navigate_left(event):
            buffer = event.current_buffer
            document = buffer.document
            buffer.cursor_position += document.get_cursor_left_position(count=event.arg)

        @bindings.add("i", filter=vi_navigation_mode | vi_selection_mode)
        def _navigate_right(event):
            buffer = event.current_buffer
            document = buffer.document
            buffer.cursor_position += document.get_cursor_right_position(count=event.arg)

        @bindings.add("I", filter=vi_navigation_mode | vi_selection_mode)
        def _end_of_screen(event):
            """
            References:
                https://github.com/prompt-toolkit/python-prompt-toolkit/blob/8f31416/src/prompt_toolkit/key_binding/bindings/vi.py#L1619
            """
            print("TODO(dmf): shift-i -", event)
