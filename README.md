# **toaster v2**

![:)](https://i.imgur.com/qsvurwi.png)

toaster is discord bot that manages new accounts when they join a server, by either:
- quarantining,
- kicking,
- banning,
- or ignoring them

it can also help prevent server nukes by quarantining users that mass-delete things such as channels.

## **main features**

the bot can do a couple of things:
- watch new accounts
- watch role deletions
- watch channel deletions
- cache emoji/sticker deletions

for example, if someone joins the server and their account age is less than what was specified during the setup of the bot, they will receive a quarantine role and their own channel.

if more than 5 users are caught by the bot's system, they are placed into a queue. when a quarantine is finished, the next user in the queue is placed into their own channel.

## **is the code good**

no