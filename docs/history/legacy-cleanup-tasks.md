- the services directory has everything. approach 
    services/
  harness/
  model-gateway/

workflow-services/
  chat-workflow/
  assistant-workflow/
  slow-workflow/

connectors/
  telegram/

mcp-servers/
  calendar-task/



- Calendar data cleanup tool

- Harness has calendar command, I think it should not know about calendar. This should be hidden in a separate class through a generic interface



- Find out if the slow execution is now everywhere or just in the test for safeplane-eval



- What I am missing is actual developer work
  - git credentials
  - repo checkout
  - work on the repo
  - pr proposal
  - run tests if available
  - select different agents with different models
  - example from old project that has the different roles


- MVP replanning
  - Developer replanning: actual developer tasks shall run on a separate repo that is added to the workspace. For that git credentials are needed as secret
  - Developer: Derive prompts and workflow from old project "conitera"
  - inspect "neighbor" repo https://github.com/stefanrossmeier/ai-craftkit/tree/main for skills, especially archdoc that needs to be updated if there were changes in between
  - not interesting: web ui, we will leave that out
  - not interesting: persistent notes. We will postpone this
  - very interesting: VPS deployment and bringup
  - very interesting: Polish for public github. Add documentation. Refine README.md so that it gives a quick introduction



  - something regarding the secrets seems to be off. I think it is now in 2 locations and hard to manage them






- The routing and routing advisor is gone missing from the MVP ladder. How shall I do different tasks through one connected telegram connector when I cannot switch workflows dynamically. This is needed.


- ADRs need to be written. Lots of decisions happened since MVP 13. I think not all of them have an ADR.
- A tool to get the evidence for the last run is necessary. I want to call a simple tool to get everything together, not a complicated Python script.
- Test coverage is not so good. especially no new acceptance tests. the MVP Tests need to be transformed into acceptance tests
- The cleanup script shall also remove old workspaces. Not running ones but old ones so that the disk usage is reduced.
- I need some documentation about the safeplace scripts. I need to be able to quickly find out what I need to call to do a certain task.
- It is necessary to have some kind of internet search possibility. In case of adding a symbol to dailydash it needs to be able to find the exact symbol that can be used. This will only work with internet access.


- Telegram connector for developer. If it is a deterministic command this might be enough. Any workflow shall have at least a command in telegram so that it can be started via a telegram chat.
- MVP Cleanup. Any scripts or docs that contain mvp are suspicious and need to be cleaned up probably. If they contain valueable information, they need to be replaced by the corresponding implementation artifact, like acceptance test, ADR, script.
- README.md needs be clean and neat. It shall contain all of the special architecture decisions as highlights, like the secret handling, the separation in containers, pydantic, ... and all the other highlights. But keep it short.
- Some quick info about how the containers work together.
- I hope we did no overfitting for the Silver Task in DailyDash in the prompts. They need to be free of both those keywords!
