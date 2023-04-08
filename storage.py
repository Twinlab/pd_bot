import json

# Read json file and return it as a dictionary
def read_json(file):
    with open(file, "r") as f:
        data = json.load(f)
        return data
    
# Write dictionary to json file
def write_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

class Users:
    
    """Users storage."""

    def __init__(self, config) -> None:
        """Initializes storage."""
        self.config = config

    def add_or_update(self, new_user: dict) -> None:
        """Adds or updates user."""
        index = self._get_user_by_id(new_user["id"])
        users = self._get_users()
        if index is not None:
            users[index] = new_user
        else:
            users.append(new_user)
        write_json(self.config, users)

    def get_or_default(self, user_id: int):
        """Returns user by id or default user."""
        index = self._get_user_by_id(user_id)
        if index is not None:
            users = self._get_users()
            return users[index]
        else:
            return {"id": user_id, "links": []}
        
    def _get_user_by_id(self, user_id: int):
        """Returns user by id."""
        for index, user in enumerate(self._get_users()):
            if user["id"] == user_id:
                return index

    def _get_users(self):
        """Returns all users."""
        return read_json(self.config)