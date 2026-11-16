# Projects and namespaces

A namespace is an external identity string such as `student_123`, `customer_983`, or `repo_mira`. It is supplied on memory and document operations and is scoped to the authenticated project.

```text
API key → project → namespace → internal MIRA workspace and API session
```

MIRA creates an internal workspace and durable API session the first time a project uses a namespace. It uses the existing MIRA repositories, lifecycle, retrieval, Knowledge Base, and worker services. An external identity never receives a MIRA login account.

The namespace key is `(project_id, namespace)`. Thus `student_123` in project `Prep AI` is isolated from `student_123` in a second project. A caller cannot select another workspace by sending an internal workspace or session ID; the key's project and the namespace resolve the storage boundary.

Use stable identifiers from your application. Do not put secrets or personal data in namespace names. Namespace strings are case-sensitive and may contain letters, numbers, `.`, `_`, `:`, and `-` (up to 128 characters).

Every API key on the same project can access the same namespace when it has the required scope. Keep project keys and scopes separate between applications and environments.
