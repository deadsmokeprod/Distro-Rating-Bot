from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    full_name = State()
    organization_code = State()


class ProfileStates(StatesGroup):
    rename = State()


class ConfirmStates(StatesGroup):
    sale_id = State()


class OrganizationStates(StatesGroup):
    inn = State()
    name = State()
    code = State()
