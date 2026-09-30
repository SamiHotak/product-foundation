"""Make a user an admin of the whole app (the /admin pages), or take it away.

    make admin email=you@example.com            give admin rights
    make admin email=you@example.com ARGS=--remove

The user must have signed up already. Admin rights are never given through the API or
the website, only with this command on the server.
"""

import argparse

from sqlalchemy import select

from app.db.session import sync_session
from app.models.user import User


def main(argv: list[str] | None = None) -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument("--remove", action="store_true", help="take admin rights away")
    args = parser.parse_args(argv)
    with sync_session() as session:
        user = session.scalar(select(User).where(User.email == args.email.strip()))
        if user is None:
            raise SystemExit(f"No user with the email {args.email}. Sign up first.")
        if user.is_demo:
            raise SystemExit("The demo user can't be an admin.")
        user.is_superuser = not args.remove
    state = "is no longer an admin" if args.remove else "is now an admin (open /admin)"
    print(f"{args.email} {state}.")


if __name__ == "__main__":
    main()
