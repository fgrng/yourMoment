# Connecting yourMoment to the project's WordPress instance

**Purpose:** yourMoment currently works only with myMoment. We are preparing it to work with the WordPress setup you run for the partner schools. Your answers decide how yourMoment models a WordPress site: which data it stores, which roles its accounts need, and what a teacher can choose when they set up monitoring. Several of these decisions are hard to undo once data exists, so we want to get them right before we build.

**From:** Fabian Grünig, **To:** technical operator of the project's WordPress setup, **How your answers will be used:** they go into the specification for the WordPress connection (GitHub issue #33 in `fgrng/yourMoment`) and into the project's design records. We will not start building until we have discussed them with you.

## Context

**yourMoment** is a separate web application that runs *next to* a writing platform and never controls it. Teachers and researchers use it. It logs in to the platform with ordinary user accounts, reads texts that students have written, generates feedback with a large language model, and can post that feedback as a comment. Three concepts come up throughout this document:

- **Monitoring Process:** a time-limited background job that a teacher or researcher sets up. It watches one **target** on the platform (for myMoment, a classroom, optionally narrowed down by writing assignment and text type). It discovers new texts there, generates a comment for each one, and either posts it or keeps it unposted for later manual review. A process always uses the accounts of exactly one platform, and that platform cannot change after the process is created.
- **AI Comment:** the record of one commenting action. It holds a frozen copy of the text as it was when processed, the generated comment, which model produced it, and the platform's comment ID once the comment is posted. Every posted AI Comment begins with a fixed German notice that it was written by AI.
- **Student Backup:** a separate feature for researchers. It uses a privileged **admin account** to save the texts of selected students on a schedule and keeps a new version whenever a text changes. Admin accounts are only ever used for the backup and never post comments.

Here is how we currently plan to connect to WordPress. Please correct anything that doesn't match your setup:
- We connect only through the **REST API with Application Passwords**. We do not scrape pages and do not use XML-RPC.
- Each WordPress installation is identified by its **base URL**. yourMoment can use several installations side by side, but each one needs its own accounts in yourMoment, and a Monitoring Process works on only one of them.
- Students are WordPress users with the role **Author** or **Contributor**, and their texts are **posts**.
- The admin account for the backup has the **Editor** role, so that it can read drafts and revisions.
- A comment the platform accepts counts as posted, even if WordPress holds it for moderation.
- Hiding a comment from everyone except the author is a myMoment feature. We assume WordPress has no equivalent.

## How to answer

We will go through this together in our meeting, and you are welcome to fill in parts beforehand. All questions together should take about 45–60 minutes. Answers like "I don't know", "not decided yet" or "it depends on the school" are useful. Please say so instead of skipping the question. Where a question has an "If …" follow-up, answer only the follow-ups that apply to your setup.

## 1. How the setup is split up (instances, sites, schools, classes)

### Is there one WordPress installation for the whole project, or several?

_Why this matters: yourMoment treats each base URL as a separate platform, with its own accounts and its own Monitoring Processes._

> 

### If there are several installations: what is each one for (per school, per class, per study phase, test vs. production)?

> 

### Is any installation a WordPress Multisite network?

_Why this matters: so far we plan to support single-site installations only. A Multisite network would change that decision._

> 

### If Multisite: what does each site in the network stand for, and does each site have its own URL (subdomain or subdirectory)?

> 

### If Multisite: are students and teachers registered network-wide, or separately on each site?

> 

### Within one site, how are schools, classes and groups kept apart (categories, tags, custom taxonomies, user groups, a plugin, separate sites)?

_Why this matters: whatever separates a class is the most likely thing a teacher would choose as the target of a Monitoring Process._

> 

### Can a student see the posts of other classes or schools?

> 

### Will the structure change during the project (new schools, new classes each term, a separate instance per study phase)?

> 

### Is there a staging or test installation that we can use during development, with test users and test content?

> 

## 2. Access and technical requirements

### What is the exact base URL of each installation (including any subdirectory)?

> 

### Is the installation self-hosted, or hosted on wordpress.com or a managed WordPress host?

> 

### Which WordPress version runs, and how are updates handled?

> 

### Is the REST API reachable from the outside without restrictions (`/wp-json/`)?

> 

### Are Application Passwords enabled for the accounts that yourMoment will use?

> 

### Do security plugins, a web application firewall, IP allowlists or basic auth block or limit REST API access?

_Why this matters: yourMoment runs on a server and makes requests at regular intervals. If those requests are blocked, monitoring fails without anyone noticing._

> 

### If there is a limit: which rate limit or request volume per minute is acceptable to you?

> 

### Is there a fixed IP address or range that we should give you for an allowlist?

> 

### Are there regular maintenance windows during which the site is unavailable?

> 

## 3. Students, their accounts, and their texts

### How do students get their WordPress accounts (created by you, by teachers, imported, single sign-on)?

> 

### Which role do students have (Author, Contributor, a custom role)?

_Why this matters: Contributors cannot publish themselves. That affects which texts are visible, and when._

> 

### Are student texts regular posts, pages, or a custom post type?

> 

### If a custom post type: what is it called, and is it exposed in the REST API?

> 

### What publishing workflow do texts go through (draft → pending review → published, scheduled, private)?

> 

### At which status should a text count as "ready for feedback"?

_Why this matters: this decides which posts a Monitoring Process picks up._

> 

### Do students edit their texts again after they have been published?

> 

### How are students identified in a way that stays stable over the project (user ID, username, pseudonym)?

_Why this matters: yourMoment stores the platform's user ID to recognise a student for the backup. If that ID changes, the student's history is lost._

> 

### Do display names or usernames contain real names, or are they pseudonymised?

> 

### Do posts contain images, embeds or attachments that matter for feedback?

> 

## 4. Grouping texts: what a teacher should be able to target

For myMoment, a teacher picks a **classroom** (required), and optionally a **writing assignment** and a **text type**. We need the WordPress equivalent.

### Which taxonomies are used on student posts (categories, tags, custom taxonomies)?

> 

### What does each of these taxonomies stand for in teaching terms (class, assignment, genre, school)?

> 

### Is every student post guaranteed to have a value for one of these taxonomies?

_Why this matters: if a value is always present, we can make it a required part of the target, so that no process quietly watches "everything"._

> 

### Can a post carry several values of the same taxonomy (for example two categories)?

> 

### Would a teacher ever want to target the texts of one specific student or a hand-picked set of students?

> 

### Is there a concept like a writing assignment, a prompt or a task that several students write about?

> 

### If yes: how is that assignment represented in WordPress?

> 

### Who creates new categories or taxonomy terms, and how often does that happen during a term?

> 

## 5. Commenting

### Which WordPress account or accounts should post the AI comments?

> 

### Should comments appear under one shared account, or under a separate account per teacher or class?

> 

### Which role should the commenting accounts have?

> 

### Is comment moderation active, so that comments are held until someone approves them?

> 

### If moderation is active: who approves comments, and should AI comments skip moderation?

> 

### Are comments open on all student posts, or closed by default or after some time?

> 

### Are threaded replies used, and should an AI comment ever be a reply to another comment?

> 

### Can students see comments on other students' posts?

> 

### Is there a way to make a comment visible only to the author and the teacher?

_Why this matters: myMoment can hide comments from other students. We currently assume WordPress has nothing like it, so the option would be switched off for WordPress._

> 

### Will the comment content be shown as plain text, or is HTML or Markdown rendered?

_Why this matters: it affects how the German AI disclosure notice at the start of each comment is shown._

> 

### Are there anti-spam plugins (such as Akismet) that might flag automated comments?

> 

## 6. Admin account and Student Backup

### Can you provide an account with the Editor role, or another role that can read every student's posts, drafts included?

> 

### Should the backup include drafts and pending posts, or only published ones?

> 

### Are post revisions enabled, and how many are kept per post?

> 

### Are posts ever deleted, or moved to the trash and then deleted?

_Why this matters: the backup should notice when a text disappears, not only when it changes._

> 

### Is there a separate backup or export on the WordPress side that we should know about or could use?

> 

## 7. Data protection and research ethics

### Which consent or data protection agreement covers storing copies of student texts outside WordPress?

> 

### Are there rules on where that data may be stored or processed (country, server, cloud services)?

> 

### Is it allowed to send student texts to an external language model provider, and if so, to which ones?

> 

### When does data have to be deleted (end of study phase, end of project, on request)?

> 

### Must posted AI comments stay on the site for the research record, or can they be removed later?

> 

## 8. Operations and timeline

### Who is the contact person for technical problems with the WordPress installation?

> 

### How should we report outages or unexpected behaviour (email, chat, issue tracker)?

> 

### When do classes start writing on the platform, and when should yourMoment be ready?

> 

### Are there phases in which no AI comments should be posted at all (exams, holidays, a control group)?

> 

### Who will create the yourMoment accounts and Monitoring Processes: you, the teachers, or the research team?

> 

## Anything else?

Is there anything about the WordPress setup, the schools or the study design that we didn't ask about but should know?

> 
