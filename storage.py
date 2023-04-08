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
        self.users = read_json(self.config["users_file"])

    def add_or_update(self, new_user: dict) -> None:
        """Adds or updates user."""
        index = self._find(new_user["id"])
        if index is not None:
            self.users[index] = new_user
        else:
            self.users.append(new_user)

    def get_or_default(self, user_id: int):
        """Returns user by id or default user."""
        index = self._find(user_id)
        if index is not None:
            return self.users[index]
        else:
            return {"id": user_id, "links": []}
        
    def _find(self, user_id: int):
        """Returns user by id."""
        for index, user in enumerate(self.users):
            if user["id"] == user_id:
                return index
