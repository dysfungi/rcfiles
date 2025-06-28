from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding.vi_state import InputMode as ViInputMode
from prompt_toolkit.filters import vi_insert_mode, vi_navigation_mode

def _configure_vi_mode():
    # https://xon.sh/envvars.html#vi-mode
    $VI_MODE = True

    # https://xon.sh/envvars.html#xonsh-copy-on-delete
    $XONSH_COPY_ON_DELETE = True

    # https://xon.sh/envvars.html#xonsh-use-system-clipboard
    $XONSH_USE_SYSTEM_CLIPBOARD = True

    @events.on_ptk_create
    def custom_keybindings(bindings, **kwargs):
        # https://python-prompt-toolkit.readthedocs.io/en/master/pages/asking_for_input.html#adding-custom-key-bindings
        # https://xon.sh/tutorial_ptk.html
        # https://python-prompt-toolkit.readthedocs.io/en/master/pages/asking_for_input.html#vi-input-mode
        #
        # Defaults: https://github.com/prompt-toolkit/python-prompt-toolkit/blob/d997aab538e434a6ca07d6bee226fd5b0628262f/src/prompt_toolkit/key_binding/bindings/vi.py#L403

        # https://python-prompt-toolkit.readthedocs.io/en/master/pages/reference.html#prompt_toolkit.key_binding.KeyBindings.add
        @bindings.add(",", "m", filter=vi_insert_mode)
        def _exit_insert_mode(event):
            # https://python-prompt-toolkit.readthedocs.io/en/master/pages/reference.html#prompt_toolkit.key_binding.vi_state.ViState
            event.cli.vi_state.input_mode = ViInputMode.NAVIGATION

        @bindings.add('l', filter=vi_navigation_mode)
        def _enter_insert_mode(event):
            event.cli.vi_state.input_mode = ViInputMode.INSERT

        @bindings.add('L', filter=vi_navigation_mode)
        def _enter_insert_mode_before_the_first_non_blank_in_the_line(event):
            buffer = event.current_buffer
            document = buffer.document
            buffer.cursor_position += document.get_start_of_line_position(
                after_whitespace=True,
            )
            enter_insert_mode(event)


if $XONSH_INTERACTIVE:
    _configure_vi_mode()
