from pytest_quint_connect import quint_contract

# Every commit in a generated history is selected by affected() and compared with the model.
test_selection = quint_contract("quint-connect.json", driver="repository_driver")
