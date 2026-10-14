; The end of the input inside a datum that (read) is reading: the error
; ends the program, even though it comes while a form is being evaluated.

(display "before")
(newline)
(write (read)) (1 2 "an unterminated string)
