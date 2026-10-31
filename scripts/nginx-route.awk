# Tokenize the shared nginx file, preserving text outside this application's
# locations. Configuration is data: no shell evaluation and no broad regex edits.
function fail(message) { print "Error: " message > "/dev/stderr"; bad=1; exit 2 }
function token(value, start, finish) { n++; t[n]=value; p[n]=start; q[n]=finish }
function lex(    i,c,start,value,quote,escaped,variable) {
    i=1
    while (i<=length(document)) {
        c=substr(document,i,1)
        if (c ~ /[ \t\r\n]/) { i++; continue }
        if (c=="#") { while(i<=length(document) && substr(document,i,1)!="\n") i++; continue }
        if (c=="{" || c=="}" || c==";") { token(c,i,i); i++; continue }
        start=i; value=""; quote=""; variable=0
        while (i<=length(document)) {
            c=substr(document,i,1)
            if (c=="\\") { value=value substr(document,i+1,1); i+=2; continue }
            if (quote!="") {
                if (c==quote) quote=""; else value=value c
                i++; continue
            }
            if (c=="\"" || c=="\047") { quote=c; i++; continue }
            if (c=="$" && substr(document,i+1,1)=="{") {
                value=value "${"; variable=1; i+=2; continue
            }
            if (variable) { value=value c; if(c=="}") variable=0; i++; continue }
            if(c ~ /[ \t\r\n{};#]/) break
            value=value c; i++
        }
        if (quote!="" || variable) fail("Unterminated quoted value in nginx configuration")
        token(value,start,i-1)
    }
}
function range(start,finish,    before,after) {
    # Include indentation/newline only when the location occupies whole lines.
    before=start
    while(before>1 && substr(document,before-1,1) ~ /[ \t]/) before--
    if(before==1 || substr(document,before-1,1)=="\n") start=before
    after=finish+1
    while(substr(document,after,1) ~ /[ \t\r]/ && after<=length(document)) after++
    if(substr(document,after,1)=="\n") finish=after
    removed++; rs[removed]=start; re[removed]=finish
}
function find_marker(marker,from,limit,    relative,found,line_start,line_end) {
    while(from<limit) {
        relative=index(substr(document,from),marker)
        if(!relative) return 0
        found=from+relative-1
        if(found>=limit) return 0
        line_start=found
        while(line_start>1 && substr(document,line_start-1,1)!="\n") line_start--
        line_end=found+length(marker)
        while(line_end<=length(document) && substr(document,line_end,1)!="\n") line_end++
        if(substr(document,line_start,found-line_start) ~ /^[ \t]*$/ &&
           substr(document,found+length(marker),line_end-found-length(marker)) ~ /^[ \t\r]*$/) return found
        from=found+length(marker)
    }
    return 0
}
{ document=document $0 "\n" }
END {
    if(bad) exit 2
    lex()
    first=1; depth=0; blocks=0
    for(i=1;i<=n;i++) {
        if(t[i]=="{") {
            b=++blocks; kind[b]=t[first]; parent[b]=stack[depth]
            begin[b]=p[first]; opening[b]=p[i]; stack[++depth]=b
            if(kind[b]=="location") {
                modifier[b]=""; k=first+1
                if(t[k]=="=" || t[k]=="^~" || t[k]=="~" || t[k]=="~*") modifier[b]=t[k++]
                path[b]=t[k]
            }
            first=i+1
        } else if(t[i]=="}") {
            if(!depth) fail("Unbalanced nginx braces")
            ending[stack[depth]]=q[i]; depth--; first=i+1
        } else if(t[i]==";") {
            b=stack[depth]
            if(kind[b]=="server" && t[first]=="server_name")
                for(k=first+1;k<i;k++) names[b]=names[b] " " t[k] " "
            if(kind[b]=="location" && t[first]=="proxy_pass") upstream[b]=t[first+1]
            if(kind[b]=="location" && t[first]=="return") {
                code[b]=t[first+1]; redirect[b]=t[first+2]
            }
            first=i+1
        }
    }
    if(depth) fail("Unbalanced nginx braces")
    for(b=1;b<=blocks;b++) if(kind[b]=="server" &&
        (server_name=="" || index(names[b]," " server_name " "))) { selected=b; matches++ }
    if(matches!=1) fail("Select exactly one server block with nginx_server in service.ini")

    marker_start="# BEGIN poe2guild " prefix
    marker_end="# END poe2guild " prefix
    offset=opening[selected]+1; managed_start=0; managed_end=0
    while(offset<ending[selected]) {
        found=find_marker(marker_start,offset,ending[selected])
        if(!found) break
        if(managed_start) fail("Duplicate poe2guild markers")
        managed_start=found
        finish=find_marker(marker_end,found,ending[selected])
        if(!finish) fail("Missing closing poe2guild marker")
        if(find_marker(marker_start,found+length(marker_start),finish)) fail("Nested poe2guild markers")
        managed_end=finish+length(marker_end)-1
        if(managed_end>=ending[selected]) fail("Marker crosses server boundary")
        # Markers must occupy their own comment lines, not quoted values.
        line_start=found
        while(line_start>1 && substr(document,line_start-1,1)!="\n") line_start--
        if(substr(document,line_start,found-line_start) !~ /^[ \t]*$/) fail("Invalid poe2guild marker")
        offset=managed_end+1
    }
    if(!managed_start && find_marker(marker_end,opening[selected],ending[selected])) fail("Orphan closing poe2guild marker")
    if(managed_start) range(managed_start,managed_end)
    for(b=1;b<=blocks;b++) if(parent[b]==selected && kind[b]=="location" &&
        (path[b]==prefix || path[b]==prefix "/")) {
        if(managed_start && begin[b]>managed_start && ending[b]<managed_end) continue
        if(path[b]==prefix "/" && modifier[b]!="=" && modifier[b]!="~" && modifier[b]!="~*") {
            if(upstream[b]!="http://" bind "/") fail("Existing location uses another upstream; configuration unchanged")
        } else if(path[b]==prefix && modifier[b]=="=" && code[b]=="301" && redirect[b]==prefix "/") {
            # Existing slash redirect belonging to this route.
        } else fail("Conflicting nginx location; configuration unchanged")
        if(action=="install") {
            if(path[b]==prefix "/") have_proxy=1; else have_redirect=1
        } else range(begin[b],ending[b])
    }
    if(action=="install" && (!have_proxy || !have_redirect)) {
        addition="    " marker_start "\n"
        if(!have_proxy) addition=addition "    location " prefix "/ {\n" \
            "        proxy_pass http://" bind "/;\n" \
            "        proxy_set_header Host $host;\n" \
            "        proxy_set_header X-Real-IP $remote_addr;\n" \
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n" \
            "    }\n"
        if(!have_redirect) addition=addition "    location = " prefix " {\n" \
            "        return 301 " prefix "/;\n" \
            "    }\n"
        addition=addition "    " marker_end "\n"
    }
    # Emit original bytes in order, skipping only the identified ranges.
    output=""; insert_at=ending[selected]
    for(i=1;i<=length(document);i++) {
        if(i==insert_at && addition!="") output=output addition
        skip=0
        for(j=1;j<=removed;j++) if(i>=rs[j] && i<=re[j]) { i=re[j]; skip=1; break }
        if(!skip) output=output substr(document,i,1)
    }
    printf "%s",output
}
