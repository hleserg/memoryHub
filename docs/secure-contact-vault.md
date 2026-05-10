# Idea: Secure Contact Vault

**Project:** Atman  
**Date:** 2026-05-11  
**Status:** Idea / not implemented

## Summary

A separate encrypted vault for contact channels and access secrets.

This is **not memory** and **not experience**. It is an address book for the agent.

## What it stores

For each contact:
- stable object identifier
- encrypted connection method
- optional access secret/token

Examples:
- Telegram ID
- Discord ID
- API key
- access token
- other safe contact handle

## What it must not store

- raw secret in memory
- raw secret in experience store
- plaintext secret in logs
- plaintext secret in narrative/reflection

Only the secret name / reference may appear in the agent's own systems.

## Access model

- read access only for agents that have secure secret storage capabilities
- humans, admins, operators, and observers should not have direct access to the vault contents
- the vault must be encrypted at rest
- access must be auditable

## Deletion protocol

If the owner of a contact or the administrator asks to delete a contact:
1. ask for confirmation
2. if confirmed, delete immediately
3. keep only a minimal audit note: contact deleted

## Possible human-facing UX

A very small web app where a person can:
- register themselves
- upload a secret/channel token
- revoke it later

This can be paired with an API for agents.

## Open question

The hardest part is safe secret intake from a human owner.
The system must allow a practical, secure way to submit secrets without exposing them to memory or experience systems.

## Notes

This idea is useful because it gives the agent independent reachability without mixing communication secrets into experiential memory.
