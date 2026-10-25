# Capstone engineering reflection — draft for the intern's review

The central design choice was to let the model interpret and route requests while
keeping facts and side effects in typed Python code. Listings come from bounded,
parameterized SQL with a restricted reader; market cards use explicit exclusions
and data dates. Reference answers cite retrieved sources. Email subjects and bodies
are rebuilt from those controlled results rather than accepted from generated text.

The browser walkthrough exposed a gap between tested tool behavior and the model's
instructions: the backend supported a keyed dashboard bucket, but the search skill
still said a missing sender made memory impossible. Updating that instruction made
the observed condo refinement retain Pasadena, budget and bedrooms. It reinforced
the value of testing the actual user path as well as unit-level behavior.

The email work makes approval a stored transition instead of a conversational claim.
The public draft hides the address; an operator reads and approves a digest; a durable
send claim prevents duplicate delivery after retries or interruptions. Offline tests
verify the ledger, refusal paths and local mail output without a provider key.

The main limitations remain visible: the MLS data is a fixed snapshot, browser
sender-less state is owner-only, search memory is process-local, and chat-provider
choice does not replace the embedding model used by an existing index. Switching
providers requires new routing and relay evidence; a green unit suite cannot supply it.

Before submission, add your own experience of the final rehearsal, the actual cost,
what you would change after the provider comparison, and the final recording link.
Those observations have intentionally not been invented here.
