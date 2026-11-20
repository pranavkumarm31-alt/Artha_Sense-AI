from .database import migrate


if __name__ == "__main__":
    applied = migrate()
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("Database schema is already up to date.")
