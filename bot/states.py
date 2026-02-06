from aiogram.fsm.state import State, StatesGroup


class RegisterStates(StatesGroup):
    waiting_name = State()
    waiting_org_code = State()


class MenuStates(StatesGroup):
    main = State()
    profile = State()
    confirm_menu = State()
    support_menu = State()
    settings_menu = State()
    org_menu = State()


class ProfileStates(StatesGroup):
    edit_name = State()


class ConfirmStates(StatesGroup):
    confirm_by_number = State()


class OrganizationStates(StatesGroup):
    add_inn = State()
    add_name = State()
    add_code = State()
