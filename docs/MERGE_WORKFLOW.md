# Merge Workflow

## Branch Structure

```
main (production)
├── repo-manager/stable (QA-verified, ready for production)
└── repo-manager/unstable (integration branch)
      ├── cto/stable (CTO-approved changes)
      └── cto/unstable (CTO integration branch)
          ├── jr-dev (development)
          ├── front-end (frontend development)
          └── back-end (backend development)
```

## Merge Flow

Changes bubble up through the branch hierarchy:

```
dev branches → cto/unstable → cto/stable → repo-manager/unstable → repo-manager/stable → main
```

### Step-by-step

1. **Developers** commit to their dev branches (`jr-dev`, `front-end`, `back-end`)
2. **Developers** open PRs from their dev branch into `cto/unstable`
3. **CTO** reviews and merges approved changes from `cto/unstable` into `cto/stable`
4. **CTO** opens a PR from `cto/stable` into `repo-manager/unstable`
5. **Repository Manager** merges into `repo-manager/unstable` and runs QA
6. After QA passes, **Repository Manager** opens a PR from `repo-manager/unstable` into `repo-manager/stable`
7. **Repository Manager** opens a PR from `repo-manager/stable` into `main` (requires CTO approval)

## Branch Protection Rules

### `main`
- Direct pushes are **blocked**
- Merges require a **pull request** with at least **1 approving review**
- Stale reviews are **dismissed** when new commits are pushed
- Enforced for **all users including admins**

### `repo-manager/stable`
- Direct pushes are **blocked**
- Merges require a **pull request** with at least **1 approving review**
- Stale reviews are **dismissed** when new commits are pushed
- Enforced for **all users including admins**
- Changes should only come from `repo-manager/unstable` after QA verification

## Guidelines

- Never push directly to `main` or `repo-manager/stable`
- All changes must go through the full merge chain
- CTO approval is required for production merges into `main`
- QA must pass before promoting from `repo-manager/unstable` to `repo-manager/stable`
- Keep branches up to date by regularly pulling from upstream
